import os
import subprocess
import tempfile
import re
import time
import traceback
from flask import Flask, jsonify, request

app = Flask(__name__)

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

@app.route('/')
def index():
    """Root endpoint"""
    return jsonify({
        "message": "Loom Processor API",
        "version": "1.0.0",
        "endpoints": ["/test-download", "/check-tools", "/simple-test"]
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
    
    return jsonify(results)

@app.route('/simple-test')
def simple_test():
    """Simple test endpoint that doesn't use any external tools."""
    return jsonify({
        "success": True,
        "message": "Simple test endpoint working"
    })

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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
