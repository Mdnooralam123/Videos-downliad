import os
import re
import subprocess
import shutil
import threading
import time
import sys
import hashlib
from datetime import datetime
from flask import Flask, request, render_template_string, send_file, jsonify

app = Flask(__name__)

# ================= CONFIG =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_FOLDER = os.path.join(BASE_DIR, "downloads")

try:
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
except PermissionError:
    DOWNLOAD_FOLDER = "/tmp/khan_downloads"
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

file_map = {}

# ================= QUALITY SIZE PRESETS =================
QUALITY_CONFIG = {
    '8K': {'height': 4320, 'target_mb': 75, 'bitrate': '15M', 'crf': 20},
    '4K': {'height': 2160, 'target_mb': 45, 'bitrate': '10M', 'crf': 22},
    '2K': {'height': 1440, 'target_mb': 28, 'bitrate': '6M', 'crf': 23},
    '1080p': {'height': 1080, 'target_mb': 18, 'bitrate': '4M', 'crf': 24},
    '720p': {'height': 720, 'target_mb': 12, 'bitrate': '2.5M', 'crf': 25},
    '480p': {'height': 480, 'target_mb': 8, 'bitrate': '1.5M', 'crf': 26}
}

# ================= CHECK DEPENDENCIES =================
def ensure_ytdlp():
    try:
        if shutil.which("yt-dlp") is None:
            subprocess.run([sys.executable, "-m", "pip", "install", "yt-dlp"], capture_output=True, check=True)
        return True
    except:
        return False

# ================= OPTIMIZE VIDEO SIZE =================
def optimize_video(input_path, output_path, quality='4K'):
    """Optimize video to target size without enhance"""
    try:
        if shutil.which("ffmpeg") is None:
            shutil.copy2(input_path, output_path)
            return output_path
        
        config = QUALITY_CONFIG.get(quality, QUALITY_CONFIG['4K'])
        height = config['height']
        bitrate = config['bitrate']
        crf = config['crf']
        
        # Check if input is already optimized
        input_size = os.path.getsize(input_path) / (1024 * 1024)
        target = config['target_mb']
        
        # If already within range, just copy
        if input_size <= target * 1.5:
            shutil.copy2(input_path, output_path)
            return output_path
        
        # Optimize with FFmpeg
        cmd = [
            "ffmpeg",
            "-i", input_path,
            "-vf", f"scale=-2:{height}:flags=fast_bilinear,format=yuv420p",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", str(crf),
            "-b:v", bitrate,
            "-maxrate", f"{int(bitrate[:-1]) * 1.5}M",
            "-bufsize", f"{int(bitrate[:-1]) * 2}M",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-y",
            output_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        
        if result.returncode != 0:
            shutil.copy2(input_path, output_path)
            return output_path
        
        # Check size and adjust if needed
        if os.path.exists(output_path):
            current_size = os.path.getsize(output_path) / (1024 * 1024)
            
            # If still too large, compress more
            if current_size > target * 1.8:
                print(f"⚠️ Size {current_size:.1f}MB > target, compressing more...")
                compress_cmd = [
                    "ffmpeg",
                    "-i", output_path,
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-crf", str(crf + 4),
                    "-b:v", f"{int(bitrate[:-1]) * 0.6}M",
                    "-maxrate", f"{int(bitrate[:-1]) * 0.9}M",
                    "-bufsize", f"{int(bitrate[:-1]) * 1.2}M",
                    "-c:a", "aac",
                    "-b:a", "96k",
                    "-movflags", "+faststart",
                    "-y",
                    output_path + ".compressed"
                ]
                subprocess.run(compress_cmd, capture_output=True, timeout=120)
                if os.path.exists(output_path + ".compressed"):
                    os.replace(output_path + ".compressed", output_path)
        
        return output_path
        
    except Exception as e:
        print(f"Optimize error: {e}")
        shutil.copy2(input_path, output_path)
        return output_path

# ================= DOWNLOAD FUNCTION =================
def download_video(url, quality='4K'):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    
    is_instagram = 'instagram' in url or 'instagr' in url
    is_youtube = 'youtube' in url or 'youtu.be' in url
    
    if not is_instagram and not is_youtube:
        return None, "Unsupported URL"
    
    prefix = 'ig' if is_instagram else 'yt'
    output_template = os.path.join(DOWNLOAD_FOLDER, f"{prefix}_{timestamp}_{url_hash}_%(id)s.%(ext)s")
    
    quality_map = {
        '8K': 'bestvideo[height<=4320][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=4320]+bestaudio/best[height<=4320]',
        '4K': 'bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=2160]+bestaudio/best[height<=2160]',
        '2K': 'bestvideo[height<=1440][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1440]+bestaudio/best[height<=1440]',
        '1080p': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]',
        '720p': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]',
        '480p': 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=480]+bestaudio/best[height<=480]'
    }
    
    format_filter = quality_map.get(quality, quality_map['4K'])
    
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-f", format_filter,
        "--merge-output-format", "mp4",
        "--referer", "https://www.instagram.com/" if is_instagram else "https://www.youtube.com/",
        "--add-header", "User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "-o", output_template,
        url
    ]
    
    if is_instagram:
        cmd.extend(["--extractor-args", "instagram:skip_login"])
    
    try:
        print(f"📥 Downloading: {url} | Quality: {quality}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        
        if result.returncode != 0:
            if is_instagram:
                return download_instagram_fallback(url)
            return None, f"Download failed"
        
        files = [f for f in os.listdir(DOWNLOAD_FOLDER) if f.startswith(f"{prefix}_{timestamp}_{url_hash}")]
        if not files:
            return None, "No file downloaded"
        
        video_file = os.path.join(DOWNLOAD_FOLDER, files[0])
        original_size = os.path.getsize(video_file) / (1024 * 1024)
        print(f"✅ Downloaded: {files[0]} ({original_size:.1f} MB)")
        
        # Optimize to target size
        print(f"📊 Optimizing to {quality} size...")
        optimized_filename = f"{quality}_{files[0]}"
        optimized_path = os.path.join(DOWNLOAD_FOLDER, optimized_filename)
        
        if shutil.which("ffmpeg"):
            optimized_path = optimize_video(video_file, optimized_path, quality)
            opt_size = os.path.getsize(optimized_path) / (1024 * 1024)
            print(f"✅ Optimized: {optimized_filename} ({opt_size:.1f} MB)")
            return optimized_path, None
        else:
            return video_file, None
        
    except subprocess.TimeoutExpired:
        return None, "Download timeout"
    except Exception as e:
        return None, str(e)

# ================= INSTAGRAM FALLBACK =================
def download_instagram_fallback(url):
    try:
        import instaloader
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_dir = os.path.join(DOWNLOAD_FOLDER, f"temp_{timestamp}")
        os.makedirs(temp_dir, exist_ok=True)
        
        shortcode_match = re.search(r'/(reel|p|tv|stories)/([^/?]+)', url)
        if not shortcode_match:
            return None, "Invalid shortcode"
        
        shortcode = shortcode_match.group(2)
        
        L = instaloader.Instaloader(
            download_videos=True,
            download_pictures=False,
            download_comments=False,
            save_metadata=False,
            filename_pattern="{shortcode}",
            dirname_pattern=temp_dir
        )
        
        post = instaloader.Post.from_shortcode(L.context, shortcode)
        L.download_post(post, target=temp_dir)
        
        for f in os.listdir(temp_dir):
            if f.endswith('.mp4'):
                src = os.path.join(temp_dir, f)
                dst = os.path.join(DOWNLOAD_FOLDER, f"ig_{timestamp}_{f}")
                os.rename(src, dst)
                shutil.rmtree(temp_dir)
                
                # Optimize
                optimized_filename = f"4K_{os.path.basename(dst)}"
                optimized_path = os.path.join(DOWNLOAD_FOLDER, optimized_filename)
                if shutil.which("ffmpeg"):
                    optimize_video(dst, optimized_path, '4K')
                    return optimized_path, None
                return dst, None
        
        shutil.rmtree(temp_dir)
        return None, "No video found"
        
    except:
        return None, "Fallback failed"

# ================= CLEANUP =================
def cleanup_old_files():
    while True:
        try:
            now = time.time()
            for filename in os.listdir(DOWNLOAD_FOLDER):
                filepath = os.path.join(DOWNLOAD_FOLDER, filename)
                if os.path.isfile(filepath):
                    if (now - os.path.getctime(filepath)) > 3600:
                        os.remove(filepath)
            time.sleep(1800)
        except:
            time.sleep(60)

# ================= HTML TEMPLATE =================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>KHAN ULTRA HD</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0a;
            font-family: -apple-system, 'Segoe UI', Roboto, sans-serif;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
            background-image: radial-gradient(circle at 20% 50%, #1a0a0a 0%, #0a0a0a 100%);
        }
        .container {
            background: rgba(26, 26, 26, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 28px;
            padding: 45px;
            max-width: 750px;
            width: 100%;
            box-shadow: 0 0 80px rgba(255, 215, 0, 0.06);
            border: 1px solid rgba(255, 215, 0, 0.08);
            animation: fadeIn 0.4s ease;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(30px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .logo { text-align: center; margin-bottom: 32px; }
        .logo h1 {
            font-size: 42px;
            font-weight: 900;
            background: linear-gradient(135deg, #FFD700, #FFA500, #FFD700);
            background-size: 200% 200%;
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            animation: gradient 3s ease infinite;
            letter-spacing: 1px;
        }
        @keyframes gradient {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }
        .logo p { 
            color: #888; 
            font-size: 15px; 
            margin-top: 6px;
            letter-spacing: 2px;
        }
        .logo .badge-4k {
            display: inline-block;
            background: linear-gradient(135deg, #FFD700, #FF8C00);
            color: #000;
            font-weight: 900;
            padding: 2px 14px;
            border-radius: 20px;
            font-size: 11px;
            margin-left: 8px;
            -webkit-text-fill-color: #000;
        }
        .input-group {
            display: flex;
            gap: 12px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        .input-group input {
            flex: 1;
            padding: 18px 22px;
            border-radius: 16px;
            border: 2px solid #2a2a2a;
            background: #111;
            color: #fff;
            font-size: 16px;
            outline: none;
            min-width: 200px;
            transition: all 0.3s;
        }
        .input-group input:focus { border-color: #FFD700; box-shadow: 0 0 30px rgba(255, 215, 0, 0.05); }
        .input-group input::placeholder { color: #555; }
        .btn {
            padding: 18px 40px;
            border: none;
            border-radius: 16px;
            background: linear-gradient(135deg, #FFD700, #F4A300);
            color: #000;
            font-weight: 800;
            font-size: 17px;
            cursor: pointer;
            transition: all 0.3s;
            white-space: nowrap;
            letter-spacing: 0.5px;
        }
        .btn:hover { transform: scale(1.03); box-shadow: 0 0 60px rgba(255, 215, 0, 0.25); }
        .btn:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }
        .btn-green {
            background: linear-gradient(135deg, #00cc44, #009933);
            color: #fff;
        }
        .btn-green:hover { box-shadow: 0 0 60px rgba(0, 204, 68, 0.25); }
        .quality-section { margin: 22px 0; display: none; }
        .quality-section.show { display: block; }
        .quality-section label { 
            color: #aaa; 
            font-size: 15px; 
            display: block; 
            margin-bottom: 14px;
            font-weight: 600;
        }
        .quality-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(115px, 1fr));
            gap: 10px;
        }
        .quality-btn {
            padding: 16px 10px;
            border: 2px solid #2a2a2a;
            border-radius: 14px;
            background: #111;
            color: #aaa;
            cursor: pointer;
            transition: all 0.3s;
            text-align: center;
            font-size: 15px;
            font-weight: 600;
        }
        .quality-btn:hover { border-color: #FFD700; background: #1a1a0a; color: #fff; transform: scale(1.04); }
        .quality-btn.selected { 
            border-color: #FFD700; 
            background: #2a2a0a; 
            color: #FFD700;
            box-shadow: 0 0 30px rgba(255, 215, 0, 0.08);
        }
        .quality-btn .sub { 
            font-size: 10px; 
            color: #555; 
            font-weight: 400;
            display: block;
            margin-top: 3px;
        }
        .quality-btn.selected .sub { color: #888; }
        .error-box {
            background: #1a0000;
            border: 1px solid #ff0000;
            border-radius: 14px;
            padding: 18px;
            color: #ff6666;
            margin-top: 18px;
            display: none;
            font-size: 14px;
        }
        .error-box.show { display: block; animation: shake 0.4s ease; }
        @keyframes shake {
            0%, 100% { transform: translateX(0); }
            25% { transform: translateX(-10px); }
            75% { transform: translateX(10px); }
        }
        .success-box {
            background: linear-gradient(135deg, #001a00, #002a00);
            border: 2px solid #00ff44;
            border-radius: 18px;
            padding: 35px;
            margin-top: 25px;
            display: none;
            animation: slideUp 0.6s ease;
        }
        @keyframes slideUp {
            from { opacity: 0; transform: translateY(40px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .success-box.show { display: block; }
        .success-box .icon { font-size: 48px; text-align: center; margin-bottom: 10px; }
        .success-box h3 { 
            color: #00ff66; 
            font-size: 24px; 
            text-align: center;
            margin-bottom: 8px;
        }
        .success-box .details { 
            color: #aaa; 
            font-size: 14px; 
            text-align: center;
            margin-bottom: 25px;
            word-break: break-all;
            background: #0a0a0a;
            padding: 12px;
            border-radius: 10px;
            border: 1px solid #1a1a1a;
        }
        .success-box .btn-download {
            display: inline-block;
            padding: 20px 60px;
            background: linear-gradient(135deg, #00cc44, #009933);
            border-radius: 16px;
            color: #fff;
            font-weight: 800;
            font-size: 22px;
            text-decoration: none;
            transition: all 0.3s;
            width: 100%;
            text-align: center;
            letter-spacing: 1px;
            border: none;
            cursor: pointer;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0% { box-shadow: 0 0 0 0 rgba(0, 204, 68, 0.4); }
            70% { box-shadow: 0 0 0 20px rgba(0, 204, 68, 0); }
            100% { box-shadow: 0 0 0 0 rgba(0, 204, 68, 0); }
        }
        .success-box .btn-download:hover { 
            transform: scale(1.02); 
            box-shadow: 0 0 80px rgba(0, 204, 68, 0.5);
        }
        .success-box .btn-download:active { transform: scale(0.98); }
        .success-box .link-box {
            margin-top: 15px;
            background: #0a0a0a;
            padding: 12px 16px;
            border-radius: 10px;
            border: 1px solid #1a1a1a;
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }
        .success-box .link-box input {
            flex: 1;
            background: transparent;
            border: none;
            color: #FFD700;
            font-size: 13px;
            outline: none;
            min-width: 150px;
            word-break: break-all;
        }
        .success-box .link-box .copy-btn {
            background: #2a2a2a;
            border: none;
            color: #aaa;
            padding: 8px 18px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 12px;
            transition: all 0.3s;
        }
        .success-box .link-box .copy-btn:hover { background: #3a3a3a; color: #fff; }
        .spinner {
            display: none;
            text-align: center;
            padding: 35px;
        }
        .spinner.show { display: block; }
        .spinner .loader {
            border: 4px solid #1a1a1a;
            border-top: 4px solid #FFD700;
            border-radius: 50%;
            width: 55px;
            height: 55px;
            animation: spin 0.6s linear infinite;
            margin: 0 auto 18px;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        .spinner p { color: #888; font-size: 15px; }
        .spinner .progress { color: #555; font-size: 13px; margin-top: 6px; }
        .supported {
            color: #444;
            font-size: 12px;
            text-align: center;
            margin-top: 22px;
            line-height: 2;
        }
        .supported span { color: #666; }
        .footer {
            text-align: center;
            color: #333;
            font-size: 12px;
            margin-top: 18px;
        }
        .footer a { color: #FFD700; text-decoration: none; }
        .badge {
            display: inline-block;
            padding: 3px 14px;
            border-radius: 20px;
            font-size: 10px;
            font-weight: 700;
            margin: 0 3px;
        }
        .badge-insta { background: #e1306c; color: #fff; }
        .badge-yt { background: #ff0000; color: #fff; }
        .badge-4k-sm { 
            background: linear-gradient(135deg, #FFD700, #FF8C00);
            color: #000;
            padding: 2px 12px;
            border-radius: 12px;
            font-size: 9px;
            font-weight: 900;
        }
        .reset-btn {
            background: none;
            border: 1px solid #333;
            color: #666;
            padding: 12px 30px;
            border-radius: 12px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.3s;
            margin-top: 18px;
            width: 100%;
        }
        .reset-btn:hover { border-color: #555; color: #aaa; background: #1a1a1a; }
        .quick-tip {
            background: rgba(255, 215, 0, 0.05);
            border: 1px solid rgba(255, 215, 0, 0.1);
            border-radius: 12px;
            padding: 12px 18px;
            margin-top: 12px;
            color: #888;
            font-size: 13px;
            text-align: center;
        }
        .quick-tip strong { color: #FFD700; }
        .size-info {
            color: #666;
            font-size: 11px;
            text-align: center;
            margin-top: 5px;
        }
        @media (max-width: 480px) {
            .container { padding: 22px; }
            .input-group input { min-width: 100%; }
            .btn { width: 100%; justify-content: center; }
            .quality-grid { grid-template-columns: repeat(auto-fill, minmax(90px, 1fr)); }
            .success-box .btn-download { font-size: 18px; padding: 16px; }
            .logo h1 { font-size: 30px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">
            <h1>🔥 KHAN <span class="badge-4k">ULTRA HD</span></h1>
            <p>Instagram + YouTube — Direct Download</p>
        </div>

        <div class="input-group">
            <input type="url" id="urlInput" 
                   placeholder="Paste Instagram Reel or YouTube URL..." 
                   required>
            <button class="btn" id="submitBtn" onclick="handleDownload()">⬇ Download</button>
        </div>

        <div class="quality-section" id="qualitySection">
            <label>🎯 Select Quality:</label>
            <div class="quality-grid" id="qualityGrid"></div>
            <div class="size-info">📊 8K: 70-80MB • 4K: 40-50MB • 2K: 25-30MB • 1080p: 15-20MB</div>
            <button class="btn btn-green" style="margin-top:15px;width:100%;" id="downloadBtn" onclick="startDownload()">
                ⚡ Generate Download Link
            </button>
        </div>

        <div class="spinner" id="spinner">
            <div class="loader"></div>
            <p id="spinnerText">⏳ Downloading & Optimizing...</p>
            <p class="progress" id="progressText">This may take a few seconds</p>
        </div>

        <div class="error-box" id="errorBox">
            <strong>❌ Error</strong><br>
            <span id="errorText"></span>
        </div>

        <div class="success-box" id="successBox">
            <div class="icon">🎬</div>
            <h3>✅ Video Ready!</h3>
            <div class="details" id="successDetails">📁 filename • 4K Ultra HD • No Watermark</div>
            
            <button onclick="triggerDownload()" class="btn-download" id="downloadBtnFinal">
                ⬇ DOWNLOAD VIDEO
            </button>
            
            <div class="link-box">
                <input type="text" id="directLink" readonly value="">
                <button class="copy-btn" onclick="copyLink()">📋 Copy</button>
            </div>
            
            <button class="reset-btn" onclick="resetForm()">🔄 Download Another Video</button>
        </div>

        <div class="quick-tip">
            💡 <strong>Direct Download</strong> — No enhancement, optimized size as per quality
        </div>

        <div class="supported">
            <span>📸 <span class="badge badge-insta">Instagram</span> Reel • Post • TV • Story</span><br>
            <span>▶️ <span class="badge badge-yt">YouTube</span> All Videos • Shorts • <span class="badge-4k-sm">8K</span> <span class="badge-4k-sm">4K</span> <span class="badge-4k-sm">2K</span> <span class="badge-4k-sm">1080p</span></span>
        </div>
        <div class="footer">
            🔥 <a href="#">@UnknownGuy9876</a> • <a href="#">@SGCodexs</a>
        </div>
    </div>

    <script>
        let currentUrl = '';
        let selectedQuality = '4K';
        let isProcessing = false;
        let downloadReady = false;
        let currentFilename = '';
        let downloadUrl = '';

        const QUALITIES = [
            { label: '⭐ 8K', value: '8K' },
            { label: '🔥 4K', value: '4K' },
            { label: '⚡ 2K', value: '2K' },
            { label: '📺 1080p', value: '1080p' },
            { label: '📺 720p', value: '720p' },
            { label: '📺 480p', value: '480p' }
        ];

        function handleDownload() {
            const url = document.getElementById('urlInput').value.trim();
            if (!url) { showError('Please enter a URL.'); return; }
            
            const isInsta = url.match(/instagram\.com\/(reel|p|tv|share|stories)\//);
            const isYT = url.match(/youtube\.com\/(watch|shorts|embed|v\/|live|playlist)|youtu\.be\//);
            
            if (!isInsta && !isYT) {
                showError('❌ Invalid URL. Use Instagram or YouTube links.');
                return;
            }
            
            currentUrl = url;
            hideError();
            hideSuccess();
            document.getElementById('qualitySection').classList.remove('show');
            downloadReady = false;
            
            const grid = document.getElementById('qualityGrid');
            grid.innerHTML = '';
            
            QUALITIES.forEach((q, index) => {
                const btn = document.createElement('div');
                btn.className = 'quality-btn' + (index === 1 ? ' selected' : '');
                btn.innerHTML = `<strong>${q.label}</strong>`;
                btn.onclick = function() {
                    document.querySelectorAll('.quality-btn').forEach(b => b.classList.remove('selected'));
                    this.classList.add('selected');
                    selectedQuality = q.value;
                };
                grid.appendChild(btn);
            });
            
            document.getElementById('qualitySection').classList.add('show');
            document.getElementById('submitBtn').textContent = '🔄 Change URL';
            document.getElementById('submitBtn').style.background = 'linear-gradient(135deg, #444, #333)';
            document.getElementById('submitBtn').style.color = '#fff';
            
            setTimeout(() => startDownload(), 300);
        }

        async function startDownload() {
            if (!currentUrl) { showError('No URL found.'); return; }
            if (isProcessing) return;
            
            isProcessing = true;
            hideError();
            hideSuccess();
            showSpinner('⏳ Downloading & Optimizing ' + selectedQuality + '...');
            document.getElementById('downloadBtn').disabled = true;
            document.getElementById('downloadBtn').textContent = '⏳ Processing...';
            document.getElementById('submitBtn').disabled = true;
            
            try {
                const response = await fetch('/api/download?url=' + encodeURIComponent(currentUrl) + '&quality=' + selectedQuality);
                const data = await response.json();
                
                hideSpinner();
                document.getElementById('downloadBtn').disabled = false;
                document.getElementById('downloadBtn').textContent = '⚡ Generate Download Link';
                document.getElementById('submitBtn').disabled = false;
                isProcessing = false;
                downloadReady = true;
                
                if (response.ok && data.success) {
                    downloadUrl = window.location.origin + data.download_url;
                    document.getElementById('directLink').value = downloadUrl;
                    document.getElementById('successDetails').innerHTML = '📁 ' + data.filename + ' • ' + selectedQuality + ' Ultra HD • No Watermark';
                    currentFilename = data.filename;
                    document.getElementById('successBox').classList.add('show');
                    
                    document.getElementById('successBox').scrollIntoView({ behavior: 'smooth', block: 'center' });
                } else {
                    showError(data.error || 'Download failed');
                }
            } catch (error) {
                hideSpinner();
                document.getElementById('downloadBtn').disabled = false;
                document.getElementById('downloadBtn').textContent = '⚡ Generate Download Link';
                document.getElementById('submitBtn').disabled = false;
                isProcessing = false;
                showError('Network error: ' + error.message);
            }
        }

        function triggerDownload() {
            if (downloadUrl) {
                window.open(downloadUrl, '_blank');
                
                const a = document.createElement('a');
                a.href = downloadUrl;
                a.download = currentFilename || 'video.mp4';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                
                const btn = document.getElementById('downloadBtnFinal');
                btn.textContent = '✅ Downloading...';
                btn.style.background = 'linear-gradient(135deg, #0088cc, #006699)';
                setTimeout(() => {
                    btn.textContent = '⬇ DOWNLOAD VIDEO';
                    btn.style.background = '';
                }, 3000);
            }
        }

        function copyLink() {
            const input = document.getElementById('directLink');
            input.select();
            input.setSelectionRange(0, 99999);
            document.execCommand('copy');
            const btn = document.querySelector('.copy-btn');
            const originalText = btn.textContent;
            btn.textContent = '✅ Copied!';
            btn.style.background = '#00cc44';
            btn.style.color = '#fff';
            setTimeout(() => {
                btn.textContent = originalText;
                btn.style.background = '';
                btn.style.color = '';
            }, 2000);
        }

        function showSpinner(msg) {
            document.getElementById('spinnerText').textContent = msg || '⏳ Processing...';
            document.getElementById('spinner').classList.add('show');
        }
        function hideSpinner() {
            document.getElementById('spinner').classList.remove('show');
        }
        function showError(msg) {
            document.getElementById('errorText').textContent = msg;
            document.getElementById('errorBox').classList.add('show');
        }
        function hideError() {
            document.getElementById('errorBox').classList.remove('show');
        }
        function hideSuccess() {
            document.getElementById('successBox').classList.remove('show');
        }
        function resetForm() {
            hideSuccess();
            hideError();
            document.getElementById('qualitySection').classList.remove('show');
            document.getElementById('urlInput').value = '';
            document.getElementById('submitBtn').textContent = '⬇ Download';
            document.getElementById('submitBtn').style.background = '';
            document.getElementById('submitBtn').style.color = '';
            document.getElementById('directLink').value = '';
            downloadUrl = '';
            currentUrl = '';
            selectedQuality = '4K';
            isProcessing = false;
            downloadReady = false;
            currentFilename = '';
            document.getElementById('downloadBtn').disabled = false;
            document.getElementById('downloadBtn').textContent = '⚡ Generate Download Link';
            document.getElementById('submitBtn').disabled = false;
            document.getElementById('urlInput').focus();
        }
    </script>
</body>
</html>
"""

# ================= FLASK ROUTES =================
@app.route('/', methods=['GET'])
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/download', methods=['GET'])
def api_download():
    url = request.args.get('url', '').strip()
    quality = request.args.get('quality', '4K')
    
    if not url:
        return jsonify({
            "success": False,
            "error": "Missing 'url' parameter",
            "usage": "/api/download?url=YOUR_URL&quality=4K"
        }), 400
    
    valid_qualities = ['8K', '4K', '2K', '1080p', '720p', '480p']
    if quality not in valid_qualities:
        return jsonify({
            "success": False,
            "error": f"Invalid quality. Use: {', '.join(valid_qualities)}"
        }), 400
    
    is_instagram = 'instagram' in url or 'instagr' in url
    is_youtube = 'youtube' in url or 'youtu.be' in url
    
    if not is_instagram and not is_youtube:
        return jsonify({
            "success": False,
            "error": "Unsupported URL. Only Instagram and YouTube are supported."
        }), 400
    
    ensure_ytdlp()
    video_file, error = download_video(url, quality)
    
    if error:
        return jsonify({"success": False, "error": error}), 400
    
    if video_file:
        filename = os.path.basename(video_file)
        file_id = hashlib.md5(filename.encode()).hexdigest()[:16]
        download_url = f"/download/{file_id}"
        
        file_map[file_id] = video_file
        file_size = os.path.getsize(video_file) / (1024 * 1024)
        
        return jsonify({
            "success": True,
            "quality": quality,
            "filename": filename.replace(f'{quality}_', ''),
            "size": f"{file_size:.1f} MB",
            "download_url": download_url,
            "message": f"Video ready in {quality} quality"
        })
    
    return jsonify({"success": False, "error": "Unknown error"}), 500

@app.route('/download/<file_id>', methods=['GET'])
def download_file(file_id):
    filepath = file_map.get(file_id)
    
    if not filepath or not os.path.exists(filepath):
        return jsonify({"success": False, "error": "File not found"}), 404
    
    return send_file(
        filepath,
        as_attachment=True,
        download_name=os.path.basename(filepath).replace(f'{os.path.basename(filepath).split("_")[0]}_', ''),
        mimetype='video/mp4'
    )

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        "status": "healthy",
        "service": "KHAN ULTRA HD",
        "version": "7.0",
        "features": ["Direct Download", "Size Optimization", "No Enhancement"],
        "supported": ["Instagram", "YouTube"],
        "size_presets": {
            "8K": "70-80 MB",
            "4K": "40-50 MB",
            "2K": "25-30 MB",
            "1080p": "15-20 MB",
            "720p": "10-15 MB",
            "480p": "5-10 MB"
        }
    })

# ================= MAIN =================
if __name__ == '__main__':
    print("🔥 KHAN ULTRA HD DOWNLOADER 🔥")
    print("=" * 60)
    print(f"📁 Download folder: {DOWNLOAD_FOLDER}")
    
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "instaloader"], capture_output=True)
        print("✅ Instaloader installed")
    except:
        pass
    
    ensure_ytdlp()
    
    if shutil.which("ffmpeg"):
        print("✅ FFmpeg available - Size Optimization active")
    else:
        print("⚠️ FFmpeg not found - Install: pkg install ffmpeg")
    
    print("=" * 60)
    print("📊 Size Presets:")
    print("   ⭐ 8K: 70-80 MB")
    print("   🔥 4K: 40-50 MB")
    print("   ⚡ 2K: 25-30 MB")
    print("   📺 1080p: 15-20 MB")
    print("   📺 720p: 10-15 MB")
    print("   📺 480p: 5-10 MB")
    print("=" * 60)
    print("📍 http://localhost:5000")
    print("📌 GET /api/download?url=URL&quality=4K")
    print("📌 GET /download/FILE_ID")
    print("=" * 60)
    
    cleanup_thread = threading.Thread(target=cleanup_old_files, daemon=True)
    cleanup_thread.start()
    
    app.run(host='0.0.0.0', port=5000, debug=False)