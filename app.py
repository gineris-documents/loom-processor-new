import os
import subprocess
import tempfile
import re
import time
import json
import traceback
from flask import Flask, jsonify, request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = Flask(__name__)

# Add this function near the top of the file
def setup_credentials():
    """Set up Google API credentials from environment variable."""
    credentials_json = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON')
    if credentials_json:
        # Create a temporary file to store the credentials
        credentials_path = os.path.join(tempfile.gettempdir(), 'service-account.json')
        with open(credentials_path, 'w') as f:
            f.write(credentials_json)
        
        # Set the environment variable to the path
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path
        return True
    return False

# Add this line near the beginning of your app
setup_credentials()

# Google Drive Setup
def get_drive_service():
    """Get an authorized Google Drive service."""
    credentials_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    if not credentials_path:
        print("Warning: GOOGLE_APPLICATION_CREDENTIALS environment variable not set.")
        return None
    
    try:
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path, 
            scopes=['https://www.googleapis.com/auth/drive']
        )
        return build('drive', 'v3', credentials=credentials)
    except Exception as e:
        print(f"Error creating Drive service: {e}")
        return None

def upload_to_drive(file_path, folder_id=None, file_name=None):
    """Upload a file to Google Drive."""
    if not os.path.exists(file_path):
        return None, f"File not found: {file_path}"
    
    service = get_drive_service()
    if not service:
        return None, "Google Drive service not available"
    
    if not folder_id:
        folder_id = os.environ.get('GOOGLE_DRIVE_FOLDER_ID')
        if not folder_id:
            return None, "No folder ID provided or configured"
    
    if not file_name:
        file_name = os.path.basename(file_path)
    
    file_metadata = {
        'name': file_name,
        'parents': [folder_id]
    }
    
    try:
        media = MediaFileUpload(file_path, resumable=True)
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id,name,webViewLink'
        ).execute()
        
        return file, None
    except Exception as e:
        return None, f"Upload failed: {str(e)}"

def extract_video_id(loom_url):
    """Extract the video ID from a Loom URL."""
    match = re.search(r'loom.com/(?:share|embed)/([a-zA-Z0-9]+)', loom_url)
    if match:
        return match.group(1)
    raise ValueError("Could not extract video ID from the provided Loom URL")

def download_loom_video(loom_url):
    """Download Loom video using yt-dlp and return path to downloaded file."""
    # Use environment variable for temp directory if available
    temp_dir = os.environ.get('TEMP_DIR', tempfile.mkdtemp())
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir, exist_ok=True)
    
    print(f"Using temporary directory: {temp_dir}")
    
    # Create a unique filename
    timestamp = int(time.time())
    output_path = os.path.join(temp_dir, f"loom_video_{timestamp}.mp4")
    
    print(f"Attempting to download video from {loom_url} to {output_path}")
    
    try:
        # Use yt-dlp to download the video
        command = [
            'yt-dlp',
            '--verbose',  # Add verbose output
            '-f', 'best',
            '-o', output_path,
            loom_url
        ]
        print(f"Running command: {' '.join(command)}")
        
        process = subprocess.run(command, capture_output=True, text=True)
        
        print(f"yt-dlp exit code: {process.returncode}")
        print(f"yt-dlp stdout: {process.stdout}")
        print(f"yt-dlp stderr: {process.stderr}")
        
        # Check if file was created successfully
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print(f"Success! Video downloaded to {output_path}")
            print(f"File size: {os.path.getsize(output_path)} bytes")
            return output_path, None
        else:
            print(f"yt-dlp command completed but file is missing or empty")
            
            # Try alternative URL
            video_id = extract_video_id(loom_url)
            alt_url = f"https://cdn.loom.com/sessions/thumbnails/{video_id}.mp4"
            alt_output_path = os.path.join(temp_dir, f"loom_direct_{timestamp}.mp4")
            
            print(f"Trying alternative URL approach: {alt_url}")
            
            curl_command = [
                'curl',
                '-L',  # Follow redirects
                '-o', alt_output_path,
                alt_url
            ]
            
            curl_process = subprocess.run(curl_command, capture_output=True, text=True)
            
            if os.path.exists(alt_output_path) and os.path.getsize(alt_output_path) > 0:
                print(f"Alternative download succeeded! File at {alt_output_path}")
                return alt_output_path, None
            
            return None, f"Failed to download video: {process.stderr}"
            
    except Exception as e:
        print(f"Error downloading video: {str(e)}")
        print(traceback.format_exc())
        return None, str(e)

def extract_frames(video_path, output_folder, interval=10):
    """Extract frames from video at specified intervals."""
    if not os.path.exists(output_folder):
        os.makedirs(output_folder, exist_ok=True)
    
    # Command to extract frames using FFmpeg
    command = [
        'ffmpeg',
        '-i', video_path,              # Input video path
        '-vf', f'fps=1/{interval}',    # Extract 1 frame every 'interval' seconds
        f'{output_folder}/frame_%04d.jpg'  # Output pattern
    ]
    
    # Run the command
    try:
        print(f"Running FFmpeg command: {' '.join(command)}")
        process = subprocess.run(command, capture_output=True, text=True)
        
        if process.returncode == 0:
            print(f"Frames extracted successfully to {output_folder}")
            return True, None
        else:
            print(f"Error extracting frames: {process.stderr}")
            return False, process.stderr
    except Exception as e:
        print(f"Exception extracting frames: {e}")
        return False, str(e)

def extract_audio(video_path, output_folder):
    """Extract audio from video for transcription."""
    if not os.path.exists(output_folder):
        os.makedirs(output_folder, exist_ok=True)
        
    audio_path = os.path.join(output_folder, "audio.wav")
    
    # Command to extract audio using FFmpeg
    command = [
        'ffmpeg',
        '-i', video_path,
        '-vn',                   # Disable video
        '-acodec', 'pcm_s16le',  # Audio codec
        '-ar', '16000',          # Sample rate
        '-ac', '1',              # Mono channel
        audio_path
    ]
    
    # Run the command
    try:
        print(f"Extracting audio from video...")
        process = subprocess.run(command, capture_output=True, text=True)
        
        if process.returncode == 0:
            print(f"Audio extracted successfully to {audio_path}")
            return audio_path, None
        else:
            print(f"Error extracting audio: {process.stderr}")
            return None, process.stderr
    except Exception as e:
        print(f"Exception extracting audio: {e}")
        return None, str(e)

@app.route('/')
def index():
    """Root endpoint"""
    return jsonify({
        "message": "Loom Processor API",
        "version": "1.0.0",
        "endpoints": [
            "/test-download - Test video download and frame extraction",
            "/process - Process a Loom video (POST)",
            "/check-tools - Check if required tools are available",
            "/test-drive - Test Google Drive integration"
        ]
    })

@app.route('/check-tools')
def check_tools():
    """Check if required tools are available."""
    results = {}
    
    # Check ffmpeg
    try:
        ffmpeg_result = subprocess.run(['which', 'ffmpeg'], capture_output=True, text=True)
        results['ffmpeg'] = {
            'available': ffmpeg_result.returncode == 0,
            'path': ffmpeg_result.stdout.strip() if ffmpeg_result.returncode == 0 else None
        }
    except Exception as e:
        results['ffmpeg'] = {'available': False, 'error': str(e)}
    
    # Check yt-dlp
    try:
        ytdlp_result = subprocess.run(['which', 'yt-dlp'], capture_output=True, text=True)
        results['yt-dlp'] = {
            'available': ytdlp_result.returncode == 0,
            'path': ytdlp_result.stdout.strip() if ytdlp_result.returncode == 0 else None
        }
    except Exception as e:
        results['yt-dlp'] = {'available': False, 'error': str(e)}
    
    # Check Google Drive API
    drive_service = get_drive_service()
    results['google_drive'] = {
        'available': drive_service is not None,
        'credentials_path': os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', 'not set'),
        'folder_id': os.environ.get('GOOGLE_DRIVE_FOLDER_ID', 'not set')
    }
    
    return jsonify(results)

@app.route('/test-download', methods=['GET'])
def test_download():
    """Test downloading a Loom video."""
    loom_url = request.args.get('url', 'https://www.loom.com/share/0cd67c5205e34420be284171e3d37060')
    
    try:
        # Extract video ID
        video_id = extract_video_id(loom_url)
        
        # Try to download
        video_path, error = download_loom_video(loom_url)
        
        if video_path:
            # Check file size
            file_size = os.path.getsize(video_path)
            
            # Try to extract a single frame
            frame_success = False
            frame_error = None
            
            try:
                frames_dir = os.path.join(os.path.dirname(video_path), "test_frames")
                os.makedirs(frames_dir, exist_ok=True)
                
                frame_path = os.path.join(frames_dir, "test_frame.jpg")
                
                # Extract a single frame
                frame_command = [
                    'ffmpeg',
                    '-i', video_path,
                    '-vframes', '1',
                    frame_path
                ]
                
                frame_process = subprocess.run(frame_command, capture_output=True, text=True)
                frame_success = os.path.exists(frame_path)
                
                if frame_success:
                    frame_error = None
                else:
                    frame_error = f"Frame extraction failed: {frame_process.stderr}"
            except Exception as e:
                frame_error = str(e)
            
            return jsonify({
                "success": True,
                "video_id": video_id,
                "video_path": video_path,
                "file_size": file_size,
                "frame_extracted": frame_success,
                "frame_error": frame_error
            })
        else:
            return jsonify({
                "success": False,
                "video_id": video_id,
                "error": error
            })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        })

@app.route('/test-drive', methods=['GET'])
def test_drive():
    """Test Google Drive integration."""
    try:
        # Create a test file
        test_file_path = os.path.join(tempfile.gettempdir(), "test_file.txt")
        with open(test_file_path, 'w') as f:
            f.write(f"Test file created at {time.time()}")
        
        # Upload to Drive
        folder_id = os.environ.get('GOOGLE_DRIVE_FOLDER_ID')
        file_info, error = upload_to_drive(test_file_path, folder_id)
        
        if file_info:
            return jsonify({
                "success": True,
                "file": file_info,
                "message": "File uploaded successfully to Google Drive"
            })
        else:
            return jsonify({
                "success": False,
                "error": error
            })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        })

@app.route('/process', methods=['POST'])
def process_video():
    """Process a Loom video and store the output in Google Drive."""
    try:
        print("Process endpoint called")
        
        # Get request data
        data = request.json
        print(f"Request data: {data}")
        
        loom_url = data.get('url')
        title = data.get('title', 'Standard Operating Procedure')
        interval = int(data.get('interval', 10))
        
        if not loom_url:
            print("Error: Missing Loom URL")
            return jsonify({"error": "Missing Loom URL"}), 400
        
        print(f"Processing video: {loom_url}, title: {title}, interval: {interval}")
        
        # Extract video ID
        try:
            video_id = extract_video_id(loom_url)
            print(f"Extracted video ID: {video_id}")
        except Exception as e:
            print(f"Error extracting video ID: {e}")
            return jsonify({"error": f"Failed to extract video ID: {str(e)}"}), 400
        
        # Create a unique output directory
        timestamp = int(time.time())
        output_dir = os.path.join(tempfile.gettempdir(), f"loom_job_{timestamp}")
        os.makedirs(output_dir, exist_ok=True)
        print(f"Created output directory: {output_dir}")
        
        frames_dir = os.path.join(output_dir, "frames")
        audio_dir = os.path.join(output_dir, "audio")
        
        # Download video
        print("Starting video download...")
        video_path, error = download_loom_video(loom_url)
        if not video_path:
            print(f"Download failed: {error}")
            return jsonify({"error": f"Failed to download video: {error}"}), 500
        
        print(f"Video downloaded to: {video_path}")
        
        # Check Google Drive credentials and folder ID
        folder_id = os.environ.get('GOOGLE_DRIVE_FOLDER_ID')
        if not folder_id:
            print("No Google Drive folder ID configured")
            return jsonify({"error": "No Google Drive folder ID configured"}), 500
        
        print(f"Using Google Drive folder ID: {folder_id}")
        
        # Test Drive service
        drive_service = get_drive_service()
        if not drive_service:
            print("Google Drive service unavailable")
            return jsonify({"error": "Google Drive service unavailable"}), 500
        
        print("Google Drive service ready")
        
        # Upload video as a test
        print("Uploading video to Drive...")
        video_file, upload_error = upload_to_drive(video_path, folder_id, f"{title}_video.mp4")
        
        if not video_file:
            print(f"Failed to upload video: {upload_error}")
            return jsonify({"error": f"Failed to upload video to Drive: {upload_error}"}), 500
        
        print(f"Video uploaded successfully: {video_file}")
        
        # Return basic success without processing frames or audio for now
        return jsonify({
            "success": True,
            "video_id": video_id,
            "title": title,
            "files": [{"type": "video", "file": video_file}]
        })
        
    except Exception as e:
        print(f"Unhandled exception in process_video: {e}")
        print(traceback.format_exc())
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500

@app.route('/test-form')
def test_form():
    """Render a simple HTML form to test the process endpoint."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Loom Processor Test</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            form { max-width: 500px; margin: 0 auto; }
            label { display: block; margin-top: 10px; }
            input, button { margin-top: 5px; padding: 5px; width: 100%; }
            button { background: #4285f4; color: white; border: none; padding: 10px; cursor: pointer; }
            #result { margin-top: 20px; white-space: pre-wrap; background: #f5f5f5; padding: 10px; }
        </style>
    </head>
    <body>
        <form id="process-form">
            <h2>Test Loom Video Processing</h2>
            <label for="url">Loom URL:</label>
            <input type="text" id="url" name="url" value="https://www.loom.com/share/0cd67c5205e34420be284171e3d37060" required>
            
            <label for="title">Title:</label>
            <input type="text" id="title" name="title" value="Test SOP" required>
            
            <label for="interval">Frame Interval (seconds):</label>
            <input type="number" id="interval" name="interval" value="10" min="1" required>
            
            <button type="submit">Process Video</button>
        </form>
        
        <div id="result"></div>
        
        <script>
            document.getElementById('process-form').addEventListener('submit', async function(e) {
                e.preventDefault();
                const resultDiv = document.getElementById('result');
                resultDiv.textContent = 'Processing...';
                
                const data = {
                    url: document.getElementById('url').value,
                    title: document.getElementById('title').value,
                    interval: parseInt(document.getElementById('interval').value)
                };
                
                try {
                    const response = await fetch('/process', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(data)
                    });
                    
                    const responseData = await response.json();
                    resultDiv.textContent = JSON.stringify(responseData, null, 2);
                } catch (error) {
                    resultDiv.textContent = 'Error: ' + error.message;
                }
            });
        </script>
    </body>
    </html>
    """
    return html

@app.route('/test-process', methods=['POST'])
def test_process():
    """Test processing a Loom video - simplified version."""
    try:
        data = request.json
        loom_url = data.get('url', 'https://www.loom.com/share/0cd67c5205e34420be284171e3d37060')
        
        print(f"Test process: Downloading video from {loom_url}")
        
        # Try to download
        video_path, error = download_loom_video(loom_url)
        
        if video_path:
            # Return success with file info
            return jsonify({
                "success": True,
                "video_path": video_path,
                "file_size": os.path.getsize(video_path)
            })
        else:
            return jsonify({
                "success": False,
                "error": error
            })
    except Exception as e:
        print(f"Exception in test_process: {e}")
        print(traceback.format_exc())
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        })

@app.route('/test-drive-simple', methods=['GET'])
def test_drive_simple():
    """Extremely simple test of Google Drive upload."""
    try:
        # Create a small text file
        test_file_path = os.path.join(tempfile.gettempdir(), "test_file.txt")
        with open(test_file_path, 'w') as f:
            f.write(f"Test file created at {time.time()}")
        
        # Get folder ID
        folder_id = os.environ.get('GOOGLE_DRIVE_FOLDER_ID')
        if not folder_id:
            return jsonify({"error": "Google Drive folder ID not configured"})
        
        # Upload to Drive
        file_info, error = upload_to_drive(test_file_path, folder_id)
        
        if file_info:
            return jsonify({
                "success": True,
                "file": file_info,
                "message": "File uploaded successfully to Google Drive"
            })
        else:
            return jsonify({
                "success": False,
                "error": error
            })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
