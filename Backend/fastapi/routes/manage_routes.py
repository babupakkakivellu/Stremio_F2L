from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from typing import Optional
import secrets

from Backend.config import Telegram
from Backend.helper.database import Database
from Backend.pyrofork.bot import StreamBot
from Backend.logger import LOGGER

router = APIRouter(tags=["File Management"])
security = HTTPBasic()
db = Database()


def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify admin credentials"""
    correct_username = secrets.compare_digest(credentials.username, Telegram.ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, Telegram.ADMIN_PASSWORD)
    
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@router.get("/manage/files", response_class=HTMLResponse)
async def manage_files_page(request: Request, username: str = Depends(verify_admin)):
    """
    Web interface for managing file-to-link uploads
    """
    html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>File Management - Telegram Stremio</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Inter', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        .header {
            background: white;
            padding: 25px 30px;
            border-radius: 12px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .header h1 {
            font-size: 24px;
            color: #1a202c;
            font-weight: 700;
        }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        
        .stat-label {
            font-size: 14px;
            color: #718096;
            margin-bottom: 5px;
        }
        
        .stat-value {
            font-size: 28px;
            font-weight: 700;
            color: #1a202c;
        }
        
        .controls {
            background: white;
            padding: 20px;
            border-radius: 12px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
        }
        
        .search-box {
            flex: 1;
            min-width: 250px;
            padding: 12px 16px;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            font-size: 14px;
            font-family: 'Inter', sans-serif;
        }
        
        .search-box:focus {
            outline: none;
            border-color: #667eea;
        }
        
        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            font-family: 'Inter', sans-serif;
        }
        
        .btn-primary {
            background: #667eea;
            color: white;
        }
        
        .btn-primary:hover {
            background: #5a67d8;
        }
        
        .btn-danger {
            background: #f56565;
            color: white;
        }
        
        .btn-danger:hover {
            background: #e53e3e;
        }
        
        .file-table {
            background: white;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
        }
        
        thead {
            background: #f7fafc;
        }
        
        th {
            padding: 16px;
            text-align: left;
            font-weight: 600;
            color: #4a5568;
            font-size: 14px;
            border-bottom: 2px solid #e2e8f0;
        }
        
        td {
            padding: 16px;
            border-bottom: 1px solid #e2e8f0;
            font-size: 14px;
            color: #2d3748;
        }
        
        tr:hover {
            background: #f7fafc;
        }
        
        .file-name {
            font-weight: 500;
            max-width: 300px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        
        .badge {
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }
        
        .badge-success {
            background: #c6f6d5;
            color: #22543d;
        }
        
        .pagination {
            display: flex;
            justify-content: center;
            gap: 10px;
            padding: 20px;
        }
        
        .page-btn {
            padding: 8px 16px;
            border: 2px solid #e2e8f0;
            background: white;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 500;
        }
        
        .page-btn.active {
            background: #667eea;
            color: white;
            border-color: #667eea;
        }
        
        .loading {
            text-align: center;
            padding: 40px;
            color: #718096;
        }
        
        @media (max-width: 768px) {
            .header {
                flex-direction: column;
                gap: 15px;
            }
            
            .stats {
                grid-template-columns: 1fr;
            }
            
            .file-table {
                overflow-x: auto;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📂 File Management</h1>
            <button class="btn btn-primary" onclick="location.reload()">🔄 Refresh</button>
        </div>
        
        <div class="stats" id="stats">
            <div class="stat-card">
                <div class="stat-label">Total Files</div>
                <div class="stat-value" id="totalFiles">-</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total Size</div>
                <div class="stat-value" id="totalSize">-</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Unique Users</div>
                <div class="stat-value" id="uniqueUsers">-</div>
            </div>
        </div>
        
        <div class="controls">
            <input type="text" class="search-box" id="searchBox" placeholder="🔍 Search files by name...">
            <button class="btn btn-primary" onclick="searchFiles()">Search</button>
            <button class="btn btn-danger" onclick="deleteSelected()">🗑️ Delete Selected</button>
        </div>
        
        <div class="file-table">
            <table>
                <thead>
                    <tr>
                        <th><input type="checkbox" id="selectAll" onchange="toggleSelectAll()"></th>
                        <th>File Name</th>
                        <th>Size</th>
                        <th>User ID</th>
                        <th>Uploaded</th>
                        <th>Access Count</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody id="fileList">
                    <tr><td colspan="7" class="loading">Loading files...</td></tr>
                </tbody>
            </table>
        </div>
        
        <div class="pagination" id="pagination"></div>
    </div>
    
    <script>
        let currentPage = 1;
        let selectedFiles = new Set();
        
        async function loadStats() {
            try {
                const response = await fetch('/api/files/stats');
                const stats = await response.json();
                
                document.getElementById('totalFiles').textContent = stats.total_files;
                document.getElementById('totalSize').textContent = stats.total_size_gb + ' GB';
                document.getElementById('uniqueUsers').textContent = stats.unique_users || '-';
            } catch (error) {
                console.error('Error loading stats:', error);
            }
        }
        
        async function loadFiles(page = 1, search = '') {
            try {
                const url = `/api/files?page=${page}&page_size=20${search ? '&search=' + encodeURIComponent(search) : ''}`;
                const response = await fetch(url);
                const data = await response.json();
                
                const tbody = document.getElementById('fileList');
                tbody.innerHTML = '';
                
                if (data.files.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="7" class="loading">No files found</td></tr>';
                    return;
                }
                
                data.files.forEach(file => {
                    const row = document.createElement('tr');
                    const uploadDate = new Date(file.uploaded_at).toLocaleDateString();
                    
                    row.innerHTML = `
                        <td><input type="checkbox" class="file-check" data-id="${file._id}" onchange="toggleFile('${file._id}')"></td>
                        <td class="file-name" title="${file.original_name}">${file.original_name}</td>
                        <td>${file.file_size_str}</td>
                        <td>${file.user_id}</td>
                        <td>${uploadDate}</td>
                        <td>${file.access_count || 0}</td>
                        <td>
                            <button class="btn btn-danger" style="padding: 6px 12px; font-size: 12px;" onclick="deleteFile('${file._id}')">Delete</button>
                        </td>
                    `;
                    tbody.appendChild(row);
                });
                
                renderPagination(data.total_count, page, 20);
            } catch (error) {
                console.error('Error loading files:', error);
                document.getElementById('fileList').innerHTML = '<tr><td colspan="7" class="loading">Error loading files</td></tr>';
            }
        }
        
        function renderPagination(total, current, pageSize) {
            const totalPages = Math.ceil(total / pageSize);
            const pagination = document.getElementById('pagination');
            pagination.innerHTML = '';
            
            if (totalPages <= 1) return;
            
            for (let i = 1; i <= totalPages; i++) {
                const btn = document.createElement('button');
                btn.className = 'page-btn' + (i === current ? ' active' : '');
                btn.textContent = i;
                btn.onclick = () => {
                    currentPage = i;
                    loadFiles(i);
                };
                pagination.appendChild(btn);
            }
        }
        
        function toggleSelectAll() {
            const selectAll = document.getElementById('selectAll');
            const checkboxes = document.querySelectorAll('.file-check');
            checkboxes.forEach(cb => {
                cb.checked = selectAll.checked;
                if (selectAll.checked) {
                    selectedFiles.add(cb.dataset.id);
                } else {
                    selectedFiles.delete(cb.dataset.id);
                }
            });
        }
        
        function toggleFile(fileId) {
            if (selectedFiles.has(fileId)) {
                selectedFiles.delete(fileId);
            } else {
                selectedFiles.add(fileId);
            }
        }
        
        function searchFiles() {
            const query = document.getElementById('searchBox').value;
            currentPage = 1;
            loadFiles(1, query);
        }
        
        async function deleteFile(fileId) {
            if (!confirm('Are you sure you want to delete this file?')) return;
            
            try {
                const response = await fetch(`/api/files/${fileId}`, {
                    method: 'DELETE'
                });
                
                if (response.ok) {
                    alert('File deleted successfully');
                    loadFiles(currentPage);
                    loadStats();
                } else {
                    alert('Failed to delete file');
                }
            } catch (error) {
                alert('Error deleting file: ' + error.message);
            }
        }
        
        async function deleteSelected() {
            if (selectedFiles.size === 0) {
                alert('No files selected');
                return;
            }
            
            if (!confirm(`Delete ${selectedFiles.size} selected files?`)) return;
            
            let deleted = 0;
            for (const fileId of selectedFiles) {
                try {
                    const response = await fetch(`/api/files/${fileId}`, {
                        method: 'DELETE'
                    });
                    if (response.ok) deleted++;
                } catch (error) {
                    console.error('Error deleting file:', error);
                }
            }
            
            alert(`Deleted ${deleted} of ${selectedFiles.size} files`);
            selectedFiles.clear();
            document.getElementById('selectAll').checked = false;
            loadFiles(currentPage);
            loadStats();
        }
        
        // Load on page load
        loadStats();
        loadFiles();
        
        // Enable search on Enter key
        document.getElementById('searchBox').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') searchFiles();
        });
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


@router.get("/api/files/stats")
async def get_file_stats(username: str = Depends(verify_admin)):
    """Get file-to-link statistics"""
    try:
        stats = await db.get_file_to_link_stats()
        
        # Get unique users count
        unique_users = set()
        for i in range(1, db.current_db_index + 1):
            db_key = f"storage_{i}"
            files = await db.dbs[db_key]["file_to_link"].find({}).to_list(length=None)
            for file in files:
                unique_users.add(file.get("user_id"))
        
        stats["unique_users"] = len(unique_users)
        return JSONResponse(content=stats)
    except Exception as e:
        LOGGER.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/files")
async def list_files(
    page: int = 1,
    page_size: int = 20,
    search: Optional[str] = None,
    username: str = Depends(verify_admin)
):
    """List all file-to-link uploads with pagination and search"""
    try:
        # Build filter
        filter_dict = {}
        if search:
            filter_dict["original_name"] = {"$regex": search, "$options": "i"}
        
        # Get files from all storage databases
        all_files = []
        for i in range(1, db.current_db_index + 1):
            db_key = f"storage_{i}"
            files = await db.dbs[db_key]["file_to_link"].find(filter_dict).to_list(length=None)
            all_files.extend(files)
        
        # Sort by upload date (newest first)
        all_files.sort(key=lambda x: x.get("uploaded_at", ""), reverse=True)
        
        # Pagination
        total_count = len(all_files)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_files = all_files[start_idx:end_idx]
        
        # Convert ObjectId to string
        from Backend.helper.database import convert_objectid_to_str
        result_files = [convert_objectid_to_str(f) for f in paginated_files]
        
        return JSONResponse(content={
            "files": result_files,
            "total_count": total_count,
            "page": page,
            "page_size": page_size
        })
    except Exception as e:
        LOGGER.error(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/files/{file_id}")
async def delete_file(file_id: str, username: str = Depends(verify_admin)):
    """Delete a file-to-link entry"""
    try:
        # Admin can delete any file, so use user_id=0 to bypass ownership check
        # Or modify delete to allow admin override
        from bson import ObjectId
        
        # Delete from database
        deleted = False
        for i in range(1, db.current_db_index + 1):
            db_key = f"storage_{i}"
            result = await db.dbs[db_key]["file_to_link"].delete_one({"_id": ObjectId(file_id)})
            if result.deleted_count > 0:
                deleted = True
                LOGGER.info(f"Admin {username} deleted file {file_id}")
                break
        
        if deleted:
            return JSONResponse(content={"success": True, "message": "File deleted"})
        else:
            raise HTTPException(status_code=404, detail="File not found")
    except Exception as e:
        LOGGER.error(f"Error deleting file: {e}")
        raise HTTPException(status_code=500, detail=str(e))
