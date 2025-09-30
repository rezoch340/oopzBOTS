"""
Web API 认证模块
提供 JWT 认证和权限验证
"""
import jwt
from datetime import datetime, timedelta
from functools import wraps
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from typing import Optional, Dict
import config

# JWT 配置（从 config.py 读取）
SECRET_KEY = config.WEB_AUTH["jwt_secret"]
ALGORITHM = config.WEB_AUTH["jwt_algorithm"]
ACCESS_TOKEN_EXPIRE_HOURS = config.WEB_AUTH["token_expire_hours"]

# 账号密码（从 config.py 读取）
ADMIN_CREDENTIALS = {
    "username": config.WEB_AUTH["username"],
    "password": config.WEB_AUTH["password"]
}


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建 JWT token
    
    Args:
        data: 要编码的数据
        expires_delta: 过期时间
    
    Returns:
        JWT token 字符串
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Optional[Dict]:
    """验证 JWT token
    
    Args:
        token: JWT token 字符串
    
    Returns:
        解码后的数据，如果验证失败返回 None
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        print("[认证] Token 已过期")
        return None
    except jwt.InvalidTokenError:
        print("[认证] Token 无效")
        return None


def verify_credentials(username: str, password: str) -> bool:
    """验证用户名和密码
    
    Args:
        username: 用户名
        password: 密码
    
    Returns:
        验证是否成功
    """
    return (username == ADMIN_CREDENTIALS["username"] and 
            password == ADMIN_CREDENTIALS["password"])


def get_token_from_request(request: Request) -> Optional[str]:
    """从请求中提取 token
    
    优先级：
    1. Cookie 中的 access_token
    2. Authorization header (Bearer token)
    
    Args:
        request: FastAPI Request 对象
    
    Returns:
        token 字符串，如果没有返回 None
    """
    # 1. 尝试从 Cookie 获取
    token = request.cookies.get("access_token")
    if token:
        return token
    
    # 2. 尝试从 Authorization header 获取
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ")[1]
    
    return None


def require_auth(func):
    """认证装饰器
    
    用于保护需要认证的 API 端点
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # 从 kwargs 中获取 request 对象
        request = kwargs.get('request')
        if not request:
            # 如果没有 request 参数，尝试从 args 中找
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
        
        if not request:
            raise HTTPException(status_code=500, detail="无法获取请求对象")
        
        # 获取 token
        token = get_token_from_request(request)
        if not token:
            raise HTTPException(
                status_code=401, 
                detail="未提供认证 token",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        # 验证 token
        payload = verify_token(token)
        if not payload:
            raise HTTPException(
                status_code=401, 
                detail="Token 无效或已过期",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        # 将用户信息添加到 request.state
        request.state.user = payload
        
        # 调用原函数
        return await func(*args, **kwargs)
    
    return wrapper


def create_login_response(username: str) -> JSONResponse:
    """创建登录响应
    
    Args:
        username: 用户名
    
    Returns:
        包含 token 的 JSONResponse
    """
    # 创建 token
    access_token = create_access_token(data={"sub": username})
    
    # 创建响应
    response = JSONResponse(content={
        "status": "success",
        "message": "登录成功",
        "token": access_token,
        "expires_in": ACCESS_TOKEN_EXPIRE_HOURS * 3600
    })
    
    # 设置 Cookie（HttpOnly 防止 XSS）
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_HOURS * 3600,
        samesite="lax"
    )
    
    return response


def create_logout_response() -> JSONResponse:
    """创建登出响应
    
    Returns:
        清除 token 的 JSONResponse
    """
    response = JSONResponse(content={
        "status": "success",
        "message": "登出成功"
    })
    
    # 清除 Cookie
    response.delete_cookie(key="access_token")
    
    return response
