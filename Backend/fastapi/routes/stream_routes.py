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
        
        # HTML5 Video Player Page (Ultra-Premium Version)
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{name} - Premium Cinema</title>
    
    <!-- External Assets -->
    <link rel="stylesheet" href="https://cdn.plyr.io/3.7.8/plyr.css" />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
    <script src="https://www.gstatic.com/cv/js/sender/v1/cast_sender.js?loadCastFramework=1"></script>
    
    <style>
        :root {{
            --primary: #9d4edd;
            --primary-gradient: linear-gradient(135deg, #9d4edd 0%, #3c096c 100%);
            --bg-dark: #10002b;
            --surface: rgba(255, 255, 255, 0.05);
            --surface-border: rgba(255, 255, 255, 0.1);
            --text-main: #e0aaff;
            --text-muted: #c77dff;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            -webkit-font-smoothing: antialiased;
        }}
        
        body {{
            background-color: var(--bg-dark);
            background-image: 
                radial-gradient(at 0% 0%, hsla(253,16%,7%,1) 0, transparent 50%), 
                radial-gradient(at 50% 0%, hsla(225,39%,30%,1) 0, transparent 50%), 
                radial-gradient(at 100% 0%, hsla(339,49%,30%,1) 0, transparent 50%);
            font-family: 'Inter', sans-serif;
            min-height: 100vh;
            display: grid;
            place-items: center;
            color: white;
            padding: 20px;
        }}
        
        .container {{
            width: 100%;
            max-width: 1100px;
            animation: fadeScale 0.8s cubic-bezier(0.2, 0.8, 0.2, 1);
        }}

        .glass-panel {{
            background: var(--surface);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid var(--surface-border);
            border-radius: 24px;
            padding: 40px;
            box-shadow: 0 40px 80px rgba(0,0,0,0.4);
        }}
        
        .header {{
            text-align: center;
            margin-bottom: 30px;
            position: relative;
        }}
        
        h1 {{
            font-weight: 800;
            font-size: 2.2rem;
            margin-bottom: 10px;
            background: linear-gradient(to right, #fff, #e0aaff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -1px;
        }}
        
        .filename-badge {{
            background: rgba(0,0,0,0.3);
            display: inline-block;
            padding: 6px 16px;
            border-radius: 50px;
            font-size: 0.9rem;
            color: var(--text-muted);
            border: 1px solid var(--surface-border);
            max-width: 100%;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}

        /* Video Player Wrapper */
        .video-container {{
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 20px 50px rgba(0,0,0,0.5);
            background: #000;
            aspect-ratio: 16/9;
            position: relative;
            margin-bottom: 30px;
            border: 1px solid rgba(255,255,255,0.05);
        }}

        video {{
            width: 100%;
            height: 100%;
            object-fit: contain;
        }}

        /* Controls Grid */
        .controls-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }}

        .action-btn {{
            background: rgba(255,255,255,0.03);
            border: 1px solid var(--surface-border);
            padding: 16px;
            border-radius: 16px;
            color: white;
            text-decoration: none;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
            font-weight: 600;
            transition: all 0.3s ease;
            cursor: pointer;
            height: 60px;
        }}

        .action-btn:hover {{
            background: rgba(255,255,255,0.1);
            transform: translateY(-2px);
            border-color: rgba(157, 78, 221, 0.5);
            box-shadow: 0 10px 20px rgba(0,0,0,0.2);
        }}

        .action-btn.primary {{
            background: var(--primary-gradient);
            border: none;
        }}
        
        .action-btn.primary:hover {{
            box-shadow: 0 10px 30px rgba(157, 78, 221, 0.4);
        }}

        /* Google Cast Customization */
        google-cast-launcher {{
            width: 24px;
            height: 24px;
            --connected-color: #fff;
            --disconnected-color: #e0aaff;
        }}
        
        .cast-btn-wrapper {{
            position: relative;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
        }}

        /* Footer */
        .footer {{
            margin-top: 40px;
            text-align: center;
            opacity: 0.5;
            font-size: 0.8rem;
            letter-spacing: 1px;
            text-transform: uppercase;
        }}

        @keyframes fadeScale {{
            0% {{ opacity: 0; transform: scale(0.95); }}
            100% {{ opacity: 1; transform: scale(1); }}
        }}

        /* Responsive Design for All Devices */
        
        /* Desktop & Laptop (992px - 1199px) */
        @media (max-width: 1199px) {{
            .container {{ max-width: 960px; }}
        }}
        
        /* Tablet Landscape (768px - 991px) */
        @media (max-width: 991px) {{
            .container {{ max-width: 720px; }}
            .glass-panel {{ padding: 30px; }}
            h1 {{ font-size: 2rem; }}
            .controls-grid {{ 
                grid-template-columns: repeat(2, 1fr); 
                gap: 12px;
            }}
        }}
        
        /* Tablet Portrait & Large Mobile (576px - 767px) */
        @media (max-width: 767px) {{
            .glass-panel {{ padding: 24px 20px; }}
            h1 {{ font-size: 1.75rem; }}
            .filename-badge {{ 
                font-size: 0.85rem; 
                padding: 5px 14px;
                max-width: 95%;
            }}
            .video-container {{ margin-bottom: 24px; }}
            .controls-grid {{ 
                grid-template-columns: 1fr; 
                gap: 10px;
            }}
            .action-btn {{
                height: 52px;
                font-size: 0.9rem;
                padding: 14px;
            }}
            .footer {{ 
                font-size: 0.7rem; 
                margin-top: 30px;
            }}
        }}
        
        /* Mobile Landscape (481px - 575px) */
        @media (max-width: 575px) {{
            body {{ padding: 15px; }}
            .glass-panel {{ 
                padding: 20px 16px; 
                border-radius: 20px;
            }}
            h1 {{ font-size: 1.5rem; }}
            .video-container {{ 
                border-radius: 14px;
                margin-bottom: 20px;
            }}
            .controls-grid {{ margin-top: 16px; }}
        }}
        
        /* Mobile Portrait (320px - 480px) */
        @media (max-width: 480px) {{
            body {{ padding: 10px; }}
            .glass-panel {{ 
                padding: 16px 12px;
                border-radius: 16px;
            }}
            h1 {{ 
                font-size: 1.3rem;
                margin-bottom: 8px;
            }}
            .filename-badge {{ 
                font-size: 0.8rem;
                padding: 4px 12px;
            }}
            .action-btn {{
                height: 48px;
                font-size: 0.85rem;
                gap: 8px;
                padding: 12px;
            }}
            .action-btn svg {{ 
                width: 20px; 
                height: 20px; 
            }}
            .footer {{ 
                font-size: 0.65rem;
                margin-top: 24px;
                letter-spacing: 0.5px;
            }}
        }}
        
        /* Touch Device Optimizations */
        @media (hover: none) and (pointer: coarse) {{
            .action-btn {{
                min-height: 48px;
                padding: 16px;
            }}
            .action-btn:active {{
                background: rgba(255,255,255,0.15);
                transform: scale(0.98);
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="glass-panel">
            <div class="header">
                <h1>Premium Cinema</h1>
                <div class="filename-badge" title="{name}">{name}</div>
            </div>

            <div class="video-container">
                <video id="player" playsinline controls preload="auto">
                    <source src="{stream_url}" type="video/mp4" />
                    <source src="{stream_url}" type="video/webm" />
                </video>
            </div>

            <div class="controls-grid">
                <a href="{stream_url}" download class="action-btn primary">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                    Download
                </a>
                
                <button onclick="copyCurrentLink()" class="action-btn">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                    Copy Link
                </button>
            </div>

            <div class="footer">
                Powered by Telegram-Stremio • High Fidelity Streaming
            </div>
        </div>
    </div>
    
    <script src="https://cdn.plyr.io/3.7.8/plyr.Polyfilled.js"></script>
    <script>
        document.addEventListener('DOMContentLoaded', () => {{
            const player = new Plyr('#player', {{
                captions: {{ active: true, update: true, language: 'en' }},
                controls: [
                    'play-large', 'restart', 'rewind', 'play', 'fast-forward', 
                    'progress', 'current-time', 'duration', 'mute', 'volume', 
                    'captions', 'settings', 'pip', 'airplay', 'google-cast', 'fullscreen'
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

        // Chromecast Implementation
        // Plyr handles the session logic automatically when 'google-cast' is in controls
        window.__onGCastApiAvailable = function(isAvailable) {{
            if (isAvailable) {{
                cast.framework.CastContext.getInstance().setOptions({{
                    receiverApplicationId: chrome.cast.media.DEFAULT_MEDIA_RECEIVER_APP_ID,
                    autoJoinPolicy: chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED
                }});
            }}
        }};
    </script>
</body>
</html>
        """
        
        return HTMLResponse(content=html_content)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading player: {str(e)}")