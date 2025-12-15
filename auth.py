"""
可复用的用户认证模块
支持基于Session的简单认证，可用于多个项目
"""

import os
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import secrets
import hashlib

# 认证配置 - 从环境变量读取，如果没有则使用默认值
AUTH_USERNAME = os.getenv('AUTH_USERNAME', 'admin')
AUTH_PASSWORD = os.getenv('AUTH_PASSWORD', 'admin123')
SESSION_SECRET = os.getenv('SESSION_SECRET', secrets.token_urlsafe(32))
SESSION_EXPIRE_HOURS = int(os.getenv('SESSION_EXPIRE_HOURS', '24'))

# 存储活跃会话（生产环境建议使用Redis）
active_sessions = {}


def hash_password(password: str) -> str:
    """对密码进行哈希处理"""
    return hashlib.sha256((password + SESSION_SECRET).encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    """验证密码"""
    return hash_password(password) == hashed


def create_session() -> str:
    """创建新的会话token"""
    token = secrets.token_urlsafe(32)
    active_sessions[token] = {
        'created_at': datetime.now(),
        'expires_at': datetime.now() + timedelta(hours=SESSION_EXPIRE_HOURS)
    }
    return token


def verify_session(token: Optional[str]) -> bool:
    """验证会话token是否有效"""
    if not token:
        return False
    
    if token not in active_sessions:
        return False
    
    session = active_sessions[token]
    
    # 检查是否过期
    if datetime.now() > session['expires_at']:
        del active_sessions[token]
        return False
    
    return True


def delete_session(token: Optional[str]):
    """删除会话"""
    if token and token in active_sessions:
        del active_sessions[token]


def authenticate(username: str, password: str) -> Optional[str]:
    """验证用户名和密码，返回session token"""
    if username == AUTH_USERNAME and password == AUTH_PASSWORD:
        return create_session()
    return None


def get_session_token(request: Request) -> Optional[str]:
    """从请求中获取session token"""
    # 优先从Cookie获取
    token = request.cookies.get('session_token')
    if token:
        return token
    
    # 从Header获取（Bearer token）
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        return auth_header[7:]
    
    return None


def require_auth(request: Request) -> bool:
    """检查请求是否需要认证"""
    # 静态资源和登录页面不需要认证
    path = request.url.path
    
    # 移除子路径前缀（如果存在）
    # 例如：/tools/tisi-helper/api/auth/login -> /api/auth/login
    root_path = os.getenv('ROOT_PATH', '')
    if root_path and path.startswith(root_path):
        path = path[len(root_path):]
        if not path.startswith('/'):
            path = '/' + path
    
    # 允许访问的路径（不需要认证）
    public_paths = [
        '/',
        '/api/auth/login',
        '/api/auth/check',
        '/static/',
        '/favicon.ico'
    ]
    
    # 检查是否是公开路径
    for public_path in public_paths:
        if path.startswith(public_path):
            return False
    
    # 其他路径需要认证
    return True


class AuthMiddleware(BaseHTTPMiddleware):
    """认证中间件"""
    
    async def dispatch(self, request: Request, call_next):
        # 检查是否需要认证
        if not require_auth(request):
            response = await call_next(request)
            return response
        
        # 获取session token
        token = get_session_token(request)
        
        # 验证session
        if not verify_session(token):
            # 如果是API请求，返回401
            if request.url.path.startswith('/api/'):
                return Response(
                    content='{"detail": "未授权，请先登录"}',
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    media_type="application/json"
                )
            # 如果是页面请求，返回登录页面（前端会处理）
            response = await call_next(request)
            return response
        
        # 认证通过，继续处理请求
        response = await call_next(request)
        return response

