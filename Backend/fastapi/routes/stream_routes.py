import math
import secrets
import mimetypes
from typing import Tuple
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse

from Backend.helper.encrypt import decode_string
from Backend.helper.exceptions import InvalidHash
from Backend.helper.custom_dl import ByteStreamer
from Backend.pyrofork.bot import StreamBot, work_loads, multi_clients

router = APIRouter(tags=["Streaming"])
class_cache = {}


def parse_range_header(range_header: str, file_size: int) -> Tuple[int, int]:
    if not range_header:
        return 0, file_size - 1
    try:
        range_value = range_header.replace("bytes=", "")
        from_str, until_str = range_value.split("-")
        from_bytes = int(from_str)
        until_bytes = int(until_str) if until_str else file_size - 1
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid Range header: {e}")

    if (until_bytes > file_size - 1) or (from_bytes < 0) or (until_bytes < from_bytes):
        raise HTTPException(
            status_code=416,
            detail="Requested Range Not Satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    return from_bytes, until_bytes


@router.get("/dl/{id}/{name}")
@router.head("/dl/{id}/{name}")
async def stream_handler(request: Request, id: str, name: str):
    decoded_data = await decode_string(id)
    if not decoded_data.get("msg_id"):
        raise HTTPException(status_code=400, detail="Missing id")

    chat_id = f"-100{decoded_data['chat_id']}"
    message = await StreamBot.get_messages(int(chat_id), int(decoded_data["msg_id"]))
    file = message.video or message.document
    file_hash = file.file_unique_id[:6]

    return await media_streamer(
        request,
        chat_id=int(chat_id),
        id=int(decoded_data["msg_id"]),
        secure_hash=file_hash
    )


async def media_streamer(
    request: Request,
    chat_id: int,
    id: int,
    secure_hash: str,
) -> StreamingResponse:
    range_header = request.headers.get("Range", "")
    index = min(work_loads, key=work_loads.get)
    faster_client = multi_clients[index]

    tg_connect = class_cache.get(faster_client)
    if not tg_connect:
        tg_connect = ByteStreamer(faster_client)
        class_cache[faster_client] = tg_connect

    file_id = await tg_connect.get_file_properties(chat_id=chat_id, message_id=id)
    if file_id.unique_id[:6] != secure_hash:
        raise InvalidHash

    file_size = file_id.file_size
    from_bytes, until_bytes = parse_range_header(range_header, file_size)

    chunk_size = 1024 * 1024
    offset = from_bytes - (from_bytes % chunk_size)
    first_part_cut = from_bytes - offset
    last_part_cut = (until_bytes % chunk_size) + 1
    req_length = until_bytes - from_bytes + 1
    part_count = math.ceil(until_bytes / chunk_size) - math.floor(offset / chunk_size)

    body = tg_connect.yield_file(
        file_id, index, offset, first_part_cut, last_part_cut, part_count, chunk_size
    )

    file_name = file_id.file_name or f"{secrets.token_hex(2)}.unknown"
    mime_type = file_id.mime_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    if not file_id.file_name and "/" in mime_type:
        file_name = f"{secrets.token_hex(2)}.{mime_type.split('/')[1]}"

    headers = {
        "Content-Type": mime_type,
        "Content-Length": str(req_length),
        "Content-Disposition": f'inline; filename="{file_name}"',
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=3600, immutable",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges",
    }
    
    if range_header:
        headers["Content-Range"] = f"bytes {from_bytes}-{until_bytes}/{file_size}"
        status_code = 206
    else:
        status_code = 200
    
    return StreamingResponse(
        status_code=status_code,
        content=body,
        headers=headers,
        media_type=mime_type,
    )


@router.get("/watch/{id}/{name}")
async def watch_handler(request: Request, id: str, name: str):
    """
    Serve an HTML page with video player for online streaming
    """
    try:
        # Decode and validate the file ID
        decoded_data = await decode_string(id)
        if not decoded_data.get("msg_id"):
            raise HTTPException(status_code=400, detail="Missing id")
        
        # Get base URL from request
        base_url = str(request.base_url).rstrip('/')
        
        # Construct the streaming URL
        stream_url = f"{base_url}/dl/{id}/{name}"
        
        # HTML5 Video Player Page (Premium Version)
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{name} - Premium Player</title>
    
    <!-- External Assets -->
    <link rel="stylesheet" href="https://cdn.plyr.io/3.7.8/plyr.css" />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
    <script src="https://www.gstatic.com/cv/js/sender/v1/cast_sender.js?loadCastFramework=1"></script>
    
    <style>
        :root {{
            --primary-gradient: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            --glass-bg: rgba(255, 255, 255, 0.1);
            --glass-border: rgba(255, 255, 255, 0.2);
            --text-main: #ffffff;
            --text-muted: rgba(255, 255, 255, 0.7);
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
        }}
        
        body {{
            background: #0f0c29;
            background: linear-gradient(to bottom, #24243e, #302b63, #0f0c29);
            font-family: 'Inter', -apple-system, sans-serif;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 20px;
            color: var(--text-main);
            overflow-x: hidden;
        }}
        
        .container {{
            max-width: 1000px;
            width: 100%;
            z-index: 1;
        }}
        
        .header {{
            text-align: center;
            margin-bottom: 40px;
            animation: fadeInDown 0.8s ease-out;
        }}
        
        .header h1 {{
            font-size: 2.5rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            margin-bottom: 12px;
            background: linear-gradient(to right, #fff, #a5a5a5);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        
        .filename {{
            font-size: 1rem;
            color: var(--text-muted);
            background: var(--glass-bg);
            padding: 8px 16px;
            border-radius: 20px;
            display: inline-block;
            backdrop-filter: blur(10px);
            border: 1px solid var(--glass-border);
            max-width: 90%;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        
        .player-card {{
            background: var(--glass-bg);
            backdrop-filter: blur(20px);
            border-radius: 24px;
            border: 1px solid var(--glass-border);
            padding: 10px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
            animation: zoomIn 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
            position: relative;
        }}

        /* Plyr Customizations */
        .plyr {{
            border-radius: 18px;
            overflow: hidden;
            --plyr-color-main: #764ba2;
        }}
        
        .controls-panel {{
            margin-top: 30px;
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            justify-content: center;
            animation: fadeInUp 0.8s ease-out;
        }}
        
        .btn {{
            padding: 14px 28px;
            border: 1px solid var(--glass-border);
            border-radius: 14px;
            font-size: 0.95rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 10px;
            background: var(--glass-bg);
            color: white;
            backdrop-filter: blur(10px);
        }}
        
        .btn:hover {{
            background: rgba(255, 255, 255, 0.2);
            transform: translateY(-3px);
            border-color: rgba(255, 255, 255, 0.4);
            box-shadow: 0 10px 20px rgba(0,0,0,0.2);
        }}
        
        .btn-primary {{
            background: var(--primary-gradient);
            border: none;
        }}
        
        .btn-primary:hover {{
            box-shadow: 0 10px 25px rgba(118, 75, 162, 0.4);
        }}

        /* Cast Button */
        google-cast-launcher {{
           --connected-color: #764ba2;
           --disconnected-color: #ffffff;
           width: 32px;
           height: 32px;
           cursor: pointer;
           display: inline-block;
           vertical-align: middle;
        }}

        .cast-wrapper {{
            display: flex;
            align-items: center;
            gap: 15px;
            background: var(--glass-bg);
            padding: 10px 20px;
            border-radius: 14px;
            border: 1px solid var(--glass-border);
        }}

        .info-footer {{
            margin-top: 40px;
            text-align: center;
            font-size: 0.85rem;
            color: var(--text-muted);
            letter-spacing: 0.05em;
        }}

        /* Animations */
        @keyframes fadeInDown {{
            from {{ opacity: 0; transform: translateY(-20px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        @keyframes fadeInUp {{
            from {{ opacity: 0; transform: translateY(20px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        @keyframes zoomIn {{
            from {{ opacity: 0; transform: scale(0.95); }}
            to {{ opacity: 1; transform: scale(1); }}
        }}

        @media (max-width: 640px) {{
            .header h1 {{ font-size: 1.8rem; }}
            .btn {{ width: 100%; justify-content: center; }}
            .container {{ padding: 10px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header class="header">
            <h1>Premium Stream</h1>
            <div class="filename" title="{name}">{name}</div>
        </header>
        
        <div class="player-card">
            <video id="player" playsinline controls preload="auto">
                <source src="{stream_url}" type="video/mp4" />
                <source src="{stream_url}" type="video/webm" />
                Your browser does not support the video tag.
            </video>
        </div>
        
        <div class="controls-panel">
            <a href="{stream_url}" download class="btn btn-primary">
                <svg width="20" height="20" fill="currentColor" viewBox="0 0 24 24"><path d="M12 21l-8-9h6V3h4v9h6l-8 9z"/></svg>
                Download
            </a>
            
            <button onclick="copyCurrentLink()" class="btn">
                <svg width="20" height="20" fill="currentColor" viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>
                Copy URL
            </button>

            <div class="cast-wrapper">
                <span>Cast to Device</span>
                <google-cast-launcher></google-cast-launcher>
            </div>
        </div>
        
        <footer class="info-footer">
            POWERED BY TELEGRAM-STREMIO CORE • ULTRALIGHT STREAMING ENGINE
        </footer>
    </div>
    
    <script src="https://cdn.plyr.io/3.7.8/plyr.Polyfilled.js"></script>
    <script>
        document.addEventListener('DOMContentLoaded', () => {{
            const player = new Plyr('#player', {{
                captions: {{ active: true, update: true, language: 'en' }},
                controls: [
                    'play-large', 'restart', 'rewind', 'play', 'fast-forward', 
                    'progress', 'current-time', 'duration', 'mute', 'volume', 
                    'captions', 'settings', 'pip', 'airplay', 'fullscreen'
                ],
                settings: ['captions', 'quality', 'speed', 'loop'],
                speed: {{ selected: 1, options: [0.5, 0.75, 1, 1.25, 1.5, 2] }}
            }});

            // Exposure for debug
            window.player = player;
        }});

        function copyCurrentLink() {{
            const link = "{stream_url}";
            navigator.clipboard.writeText(link).then(() => {{
                // Subtle toast alternative
                const btn = event.currentTarget;
                const originalText = btn.innerHTML;
                btn.innerHTML = '✅ Copied!';
                setTimeout(() => btn.innerHTML = originalText, 2000);
            }}).catch(err => {{
                alert('Failed to copy link');
            }});
        }}

        // Chromecast Init
        window.__onGCastApiAvailable = function(isAvailable) {{
            if (isAvailable) {{
                initializeCastApi();
            }}
        }};

        function initializeCastApi() {{
            cast.framework.CastContext.getInstance().setOptions({{
                receiverApplicationId: chrome.cast.media.DEFAULT_MEDIA_RECEIVER_APP_ID,
                autoJoinPolicy: chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED
            }});
        }}
    </script>
</body>
</html>
        """
        
        return HTMLResponse(content=html_content)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading player: {str(e)}")