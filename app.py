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
        # Get request data
        data = request.json
        loom_url = data.get('url')
        title = data.get('title', 'Standard Operating Procedure')
        interval = int(data.get('interval', 10))
        
        if not loom_url:
            return jsonify({"error": "Missing Loom URL"}), 400
        
        # Extract video ID
        video_id = extract_video_id(loom_url)
        
        # Create a unique output directory
        timestamp = int(time.time())
        output_dir = os.path.join(tempfile.gettempdir(), f"loom_job_{timestamp}")
        os.makedirs(output_dir, exist_ok=True)
        
        frames_dir = os.path.join(output_dir, "frames")
        audio_dir = os.path.join(output_dir, "audio")
        
        # Download video
        video_path, error = download_loom_video(loom_url)
        if not video_path:
            return jsonify({"error": f"Failed to download video: {error}"}), 500
        
        # Extract frames
        frames_success, frames_error = extract_frames(video_path, frames_dir, interval)
        if not frames_success:
            return jsonify({"error": f"Failed to extract frames: {frames_error}"}), 500
        
        # Extract audio
        audio_path, audio_error = extract_audio(video_path, audio_dir)
        if not audio_path:
            return jsonify({"error": f"Failed to extract audio: {audio_error}"}), 500
        
        # Upload frames to Google Drive
        folder_id = os.environ.get('GOOGLE_DRIVE_FOLDER_ID')
        result_files = []
        
        # Upload video
        video_file, video_error = upload_to_drive(video_path, folder_id, f"{title}_video.mp4")
        if video_file:
            result_files.append({"type": "video", "file": video_file})
        
        # Upload frames
        for frame_file in os.listdir(frames_dir):
            if frame_file.endswith('.jpg'):
                frame_path = os.path.join(frames_dir, frame_file)
                frame_info, frame_error = upload_to_drive(frame_path, folder_id, f"{title}_{frame_file}")
                if frame_info:
                    result_files.append({"type": "frame", "file": frame_info})
        
        # Upload audio
        audio_file, audio_error = upload_to_drive(audio_path, folder_id, f"{title}_audio.wav")
        if audio_file:
            result_files.append({"type": "audio", "file": audio_file})
        
        return jsonify({
            "success": True,
            "video_id": video_id,
            "title": title,
            "files": result_files
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
