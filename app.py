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
        print(f"Loading credentials from: {credentials_path}")
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path, 
            scopes=['https://www.googleapis.com/auth/drive']
        )
        print(f"Credentials loaded successfully. Service account: {credentials.service_account_email}")
        return build('drive', 'v3', credentials=credentials)
    except Exception as e:
        print(f"Error creating Drive service: {e}")
        traceback.print_exc()
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
        print(f"Using folder ID from environment: {folder_id}")
        if not folder_id:
            return None, "No folder ID provided or configured"
    
    if not file_name:
        file_name = os.path.basename(file_path)
    
    print(f"Uploading file: {file_path} to folder: {folder_id} with name: {file_name}")
    
    file_metadata = {
        'name': file_name,
        'parents': [folder_id]
    }
    
    try:
        # First try to verify the folder exists
        try:
            folder = service.files().get(fileId=folder_id).execute()
            print(f"Found folder: {folder.get('name', 'unknown')} ({folder_id})")
        except Exception as e:
            print(f"Failed to verify folder: {e}")
            # Try to list all accessible folders
            results = service.files().list(
                q="mimeType='application/vnd.google-apps.folder'",
                fields="files(id, name)"
            ).execute()
            folders = results.get('files', [])
            print(f"Accessible folders: {folders}")
        
        # Proceed with upload
        media = MediaFileUpload(file_path, resumable=True)
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id,name,webViewLink'
        ).execute()
        
        print(f"File uploaded successfully: {file}")
        return file, None
    except Exception as e:
        print(f"Upload failed: {e}")
        traceback.print_exc()
        return None, f"Upload failed: {str(e)}"

def upload_to_shared_drive(file_path, drive_id=None, folder_id=None, file_name=None):
    """Upload a file to a Google Shared Drive."""
    if not os.path.exists(file_path):
        return None, f"File not found: {file_path}"
    
    service = get_drive_service()
    if not service:
        return None, "Google Drive service not available"
    
    drive_id = drive_id or os.environ.get('GOOGLE_SHARED_DRIVE_ID')
    folder_id = folder_id or os.environ.get('GOOGLE_DRIVE_FOLDER_ID')
    
    print(f"Using shared drive ID: {drive_id}, folder ID: {folder_id}")
    
    if not drive_id:
        return None, "No shared drive ID provided or configured"
    
    if not file_name:
        file_name = os.path.basename(file_path)
    
    print(f"Uploading file: {file_path} to shared drive: {drive_id}, folder: {folder_id}, name: {file_name}")
    
    # For Shared Drives, we need to use a different approach
    file_metadata = {
        'name': file_name,
        'parents': []
    }
    
    # If folder ID is provided, add it to parents, otherwise use the root of the shared drive
    if folder_id:
        file_metadata['parents'] = [folder_id]
    else:
        file_metadata['parents'] = [drive_id]
    
    try:
        media = MediaFileUpload(file_path, resumable=True)
        
        # For Shared Drives, use supportsAllDrives=True
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id,name,webViewLink',
            supportsAllDrives=True
        ).execute()
        
        print(f"File uploaded successfully: {file}")
        return file, None
    except Exception as e:
        print(f"Upload failed: {e}")
        traceback.print_exc()
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
            "/test-drive - Test Google Drive integration",
            "/test-shared-drive - Test Shared Drive integration",
            "/list-drives - List available Shared Drives",
            "/list-folders - List folders in a Shared Drive"
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
        'folder_id': os.environ.get('GOOGLE_DRIVE_FOLDER_ID', 'not set'),
        'shared_drive_id': os.environ.get('GOOGLE_SHARED_DRIVE_ID', 'not set')
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

@app.route('/test-shared-drive', methods=['GET'])
def test_shared_drive():
    """Test uploading to a Shared Drive."""
    try:
        # Create a small text file
        test_file_path = os.path.join(tempfile.gettempdir(), "test_file.txt")
        with open(test_file_path, 'w') as f:
            f.write(f"Test file created at {time.time()}")
        
        # Get drive and folder IDs
        drive_id = os.environ.get('GOOGLE_SHARED_DRIVE_ID')
        folder_id = os.environ.get('GOOGLE_DRIVE_FOLDER_ID', None)  # Optional for Shared Drives
        
        if not drive_id:
            return jsonify({"error": "Google Shared Drive ID not configured"})
        
        # Upload to Drive
        file_info, error = upload_to_shared_drive(test_file_path, drive_id, folder_id)
        
        if file_info:
            return jsonify({
                "success": True,
                "file": file_info,
                "message": "File uploaded successfully to Google Shared Drive"
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

@app.route('/list-drives', methods=['GET'])
def list_drives():
    """List all accessible Shared Drives."""
    try:
        service = get_drive_service()
        if not service:
            return jsonify({"error": "Google Drive service not available"})
        
        # List all Shared Drives available to the service account
        drives = []
        page_token = None
        
        while True:
            try:
                response = service.drives().list(
                    pageSize=100,
                    fields="nextPageToken, drives(id, name)",
                    pageToken=page_token
                ).execute()
                
                drives.extend(response.get('drives', []))
                page_token = response.get('nextPageToken')
                
                if not page_token:
                    break
            except Exception as e:
                print(f"Error listing drives: {e}")
                return jsonify({"error": f"Failed to list drives: {str(e)}"})
        
        return jsonify({
            "success": True,
            "drives": drives
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        })

@app.route('/list-folders', methods=['GET'])
def list_folders():
    """List all accessible folders in a Shared Drive."""
    try:
        service = get_drive_service()
        if not service:
            return jsonify({"error": "Google Drive service not available"})
        
        drive_id = request.args.get('drive_id') or os.environ.get('GOOGLE_SHARED_DRIVE_ID')
        if not drive_id:
            return jsonify({"error": "No drive ID provided"})
        
        # Query for folders in the specified drive
        query = "mimeType='application/vnd.google-apps.folder'"
        
        folders = []
        page_token = None
        
        while True:
            try:
                response = service.files().list(
                    q=query,
                    driveId=drive_id,
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                    corpora="drive",
                    fields="nextPageToken, files(id, name, parents)",
                    pageToken=page_token
                ).execute()
                
                folders.extend(response.get('files', []))
                page_token = response.get('nextPageToken')
                
                if not page_token:
                    break
            except Exception as e:
                print(f"Error listing folders: {e}")
                return jsonify({"error": f"Failed to list folders: {str(e)}"})
        
        return jsonify({
            "success": True,
            "drive_id": drive_id,
            "folders": folders
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
        drive_id = os.environ.get('GOOGLE_SHARED_DRIVE_ID')
        
        if not folder_id and not drive_id:
            print("No Google Drive folder ID or Shared Drive ID configured")
            return jsonify({"error": "No Google Drive folder ID or Shared Drive ID configured"}), 500
        
        # Test Drive service
        drive_service = get_drive_service()
        if not drive_service:
            print("Google Drive service unavailable")
            return jsonify({"error": "Google Drive service unavailable"}), 500
        
        print("Google Drive service ready")
        
        # Create frames directory and extract frames
        os.makedirs(frames_dir, exist_ok=True)
        print(f"Created frames directory: {frames_dir}")
        
        # Extract frames at specified interval
        print(f"Extracting frames at {interval} second intervals...")
        frames_success, frames_error = extract_frames(video_path, frames_dir, interval)
        if not frames_success:
            print(f"Frame extraction failed: {frames_error}")
            return jsonify({"error": f"Failed to extract frames: {frames_error}"}), 500
        
        # Create audio directory
        os.makedirs(audio_dir, exist_ok=True)
        print(f"Created audio directory: {audio_dir}")
        
        # Extract audio
        print("Extracting audio...")
        audio_path, audio_error = extract_audio(video_path, audio_dir)
        if not audio_path:
            print(f"Audio extraction failed: {audio_error}")
            return jsonify({"error": f"Failed to extract audio: {audio_error}"}), 500
        
        # Upload files to Drive
        print("Uploading files to Drive...")
        uploaded_files = []
        
        # Upload video
        if drive_id:
            video_file, video_error = upload_to_shared_drive(
                video_path, drive_id, folder_id, f"{title}_video.mp4"
            )
        else:
            video_file, video_error = upload_to_drive(
                video_path, folder_id, f"{title}_video.mp4"
            )
        
        if video_file:
            uploaded_files.append({"type": "video", "file": video_file})
            print("Video uploaded successfully")
        else:
            print(f"Failed to upload video: {video_error}")
        
        # Upload extracted frames
        print(f"Uploading extracted frames...")
        frame_files = []
        for frame_file in sorted(os.listdir(frames_dir)):
            if frame_file.endswith('.jpg'):
                frame_path = os.path.join(frames_dir, frame_file)
                if drive_id:
                    file_info, error = upload_to_shared_drive(
                        frame_path, drive_id, folder_id, f"{title}_{frame_file}"
                    )
                else:
                    file_info, error = upload_to_drive(
                        frame_path, folder_id, f"{title}_{frame_file}"
                    )
                
                if file_info:
                    frame_files.append({"type": "frame", "file": file_info})
                    print(f"Uploaded frame: {frame_file}")
                else:
                    print(f"Failed to upload frame {frame_file}: {error}")
        
        # Add frame files to the uploaded_files list
        uploaded_files.extend(frame_files)
        
        # Upload audio file
        print("Uploading audio file...")
        if drive_id:
            audio_file, audio_error = upload_to_shared_drive(
                audio_path, drive_id, folder_id, f"{title}_audio.wav"
            )
        else:
            audio_file, audio_error = upload_to_drive(
                audio_path, folder_id, f"{title}_audio.wav"
            )
        
        if audio_file:
            uploaded_files.append({"type": "audio", "file": audio_file})
            print("Audio file uploaded successfully")
        else:
            print(f"Failed to upload audio file: {audio_error}")
        
        # Return successful response
        return jsonify({
            "success": True,
            "video_id": video_id,
            "title": title,
            "files": uploaded_files
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
        
        # Check if we're using regular Drive or Shared Drive
        drive_id = os.environ.get('GOOGLE_SHARED_DRIVE_ID')
        folder_id = os.environ.get('GOOGLE_DRIVE_FOLDER_ID')
        
        # Ensure we have either a folder ID or a drive ID
        if not drive_id and not folder_id:
            return jsonify({"error": "No Google Drive folder ID or Shared Drive ID configured"})
        
        # Upload to Drive
        file_info = None
        error = None
        
        if drive_id:
            # Use Shared Drive
            file_info, error = upload_to_shared_drive(test_file_path, drive_id, folder_id)
        else:
            # Use regular Drive
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

@app.route('/test-drive-debug', methods=['GET'])
def test_drive_debug():
    """Debugging test for Google Drive."""
    try:
        # Report environment info
        credentials_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', 'not set')
        folder_id = os.environ.get('GOOGLE_DRIVE_FOLDER_ID', 'not set')
        drive_id = os.environ.get('GOOGLE_SHARED_DRIVE_ID', 'not set')
        
        # Check if credentials file exists
        creds_exist = os.path.exists(credentials_path) if credentials_path != 'not set' else False
        
        # Try to get Drive service
        service = get_drive_service()
        service_available = service is not None
        
        # Try to get service account email
        service_account_email = "unknown"
        try:
            if service_available:
                # This will fail if we can't access the service account info
                about = service.about().get(fields="user").execute()
                service_account_email = about.get("user", {}).get("emailAddress", "unknown")
        except Exception as e:
            print(f"Failed to get service account email: {e}")
        
        # Return debug info
        return jsonify({
            "credentials_path": credentials_path,
            "credentials_exist": creds_exist,
            "folder_id": folder_id,
            "shared_drive_id": drive_id,
            "service_available": service_available,
            "service_account_email": service_account_email
        })
    except Exception as e:
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
