import os
import csv
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import uuid

# 加载环境变量
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # 如果没有安装python-dotenv，尝试直接读取.env文件
    env_file = Path('.env')
    if env_file.exists():
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

from fastapi import FastAPI, File, UploadFile, HTTPException, Query, Form
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
import uvicorn
from docx import Document
from PIL import Image
import io
import zipfile
import aiofiles

# 导入认证模块
from auth import (
    authenticate, verify_session, get_session_token, delete_session,
    AuthMiddleware, require_auth
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 创建必要的目录
for dir_name in ['uploads', 'outputs', 'history', 'logs']:
    Path(dir_name).mkdir(exist_ok=True)

# 支持子路径部署
import os
ROOT_PATH = os.getenv('ROOT_PATH', '')

app = FastAPI(
    title="TISI 文章助手工具",
    root_path=ROOT_PATH  # 支持子路径部署，如 /tools/tisi-helper
)

# 添加认证中间件
app.add_middleware(AuthMiddleware)

# 配置
MAX_WEBP_FILES = 20  # 可配置的WebP上传上限
HISTORY_CSV = 'history/seo_history.csv'

# AI API 配置 - 支持三个提供商
# 可选值: 'qwen' (通义千问), 'deepseek' (DeepSeek), 'doubao' (豆包)
# 默认使用通义千问
AI_API_PROVIDER = os.getenv('AI_API_PROVIDER', 'qwen')  # 默认使用通义千问

# 提示词配置 - 三个模型可以有不同的提示词
PROMPT_CONFIG = {
    'qwen': """你是一个专业的SEO内容优化专家。请根据以下文章内容，生成高质量的SEO信息。

【文章标题】
{title}

【文章内容】
{content}

【任务要求】
请仔细阅读文章标题和内容，理解文章的核心主题和关键信息，然后生成以下SEO内容：

1. **摘要（summary）**：
   - 生成一段简洁、准确、吸引人的中文摘要
   - 必须准确概括文章的核心内容和主要观点
   - 字数严格控制在68字以内（包括标点符号）
   - 语言要流畅自然，具有吸引力
   - 不要使用"本文"、"文章"等词开头

2. **关键词（keywords）**：
   - 根据文章标题、内容和摘要，提取3-6个最相关的关键词
   - 关键词要符合Google SEO规范，具有搜索价值
   - 优先选择用户可能搜索的核心词汇
   - 使用英文逗号,隔开，不要有空格
   - 格式示例：关键词1,关键词2,关键词3

3. **Slug（slug）**：
   - 根据文章的标题和核心内容，生成一个适用于URL的英文slug
   - 全部使用小写字母
   - 只包含字母、数字和连字符（-）
   - 长度控制在30-50个字符之间
   - 要简洁、有意义、易于理解
   - 格式示例：article-title-seo-friendly

【输出格式】
请严格按照以下JSON格式返回，不要添加任何其他文字说明：
{{
    "summary": "这里填写68字以内的中文摘要",
    "keywords": "关键词1,关键词2,关键词3",
    "slug": "article-slug-format"
}}

请开始生成：""",
    'deepseek': """你是一个专业的SEO内容优化专家。请根据以下文章内容，生成高质量的SEO信息。

【文章标题】
{title}

【文章内容】
{content}

【任务要求】
请仔细阅读文章标题和内容，理解文章的核心主题和关键信息，然后生成以下SEO内容：

1. **摘要（summary）**：
   - 生成一段简洁、准确、吸引人的中文摘要
   - 必须准确概括文章的核心内容和主要观点
   - 字数严格控制在68字以内（包括标点符号）
   - 语言要流畅自然，具有吸引力
   - 不要使用"本文"、"文章"等词开头

2. **关键词（keywords）**：
   - 根据文章标题、内容和摘要，提取3-6个最相关的关键词
   - 关键词要符合Google SEO规范，具有搜索价值
   - 优先选择用户可能搜索的核心词汇
   - 使用英文逗号,隔开，不要有空格
   - 格式示例：关键词1,关键词2,关键词3

3. **Slug（slug）**：
   - 根据文章的标题和核心内容，生成一个适用于URL的英文slug
   - 全部使用小写字母
   - 只包含字母、数字和连字符（-）
   - 长度控制在30-50个字符之间
   - 要简洁、有意义、易于理解
   - 格式示例：article-title-seo-friendly

【输出格式】
请严格按照以下JSON格式返回，不要添加任何其他文字说明：
{{
    "summary": "这里填写68字以内的中文摘要",
    "keywords": "关键词1,关键词2,关键词3",
    "slug": "article-slug-format"
}}

请开始生成：""",
    'doubao': """你是一个专业的SEO内容优化专家。请根据以下文章内容，生成高质量的SEO信息。

【文章标题】
{title}

【文章内容】
{content}

【任务要求】
请仔细阅读文章标题和内容，理解文章的核心主题和关键信息，然后生成以下SEO内容：

1. **摘要（summary）**：
   - 生成一段简洁、准确、吸引人的中文摘要
   - 必须准确概括文章的核心内容和主要观点
   - 字数严格控制在68字以内（包括标点符号）
   - 语言要流畅自然，具有吸引力
   - 不要使用"本文"、"文章"等词开头

2. **关键词（keywords）**：
   - 根据文章标题、内容和摘要，提取3-6个最相关的关键词
   - 关键词要符合Google SEO规范，具有搜索价值
   - 优先选择用户可能搜索的核心词汇
   - 使用英文逗号,隔开，不要有空格
   - 格式示例：关键词1,关键词2,关键词3

3. **Slug（slug）**：
   - 根据文章的标题和核心内容，生成一个适用于URL的英文slug
   - 全部使用小写字母
   - 只包含字母、数字和连字符（-）
   - 长度控制在30-50个字符之间
   - 要简洁、有意义、易于理解
   - 格式示例：article-title-seo-friendly

【输出格式】
请严格按照以下JSON格式返回，不要添加任何其他文字说明：
{{
    "summary": "这里填写68字以内的中文摘要",
    "keywords": "关键词1,关键词2,关键词3",
    "slug": "article-slug-format"
}}

请开始生成："""
}

# 提示词密码（可以通过环境变量配置）
PROMPT_PASSWORD = os.getenv('PROMPT_PASSWORD', '112346')

# 初始化历史记录CSV文件（如果不存在）
if not Path(HISTORY_CSV).exists():
    with open(HISTORY_CSV, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['时间', '标题', '摘要', '关键词', 'slug', '文章附加', 'AI模型'])

# AI生成函数 - 支持多个API提供商
async def generate_seo_content(title: str, content: str, provider: str = None) -> dict:
    """生成SEO内容：摘要、关键词、slug
    
    Args:
        title: 文章标题
        content: 文章内容
        provider: API提供商，可选值: 'qwen', 'deepseek', 'doubao'
                  如果为None，则使用配置的默认提供商
    """
    if provider is None:
        provider = AI_API_PROVIDER
    
    # 获取对应模型的提示词模板
    prompt_template = PROMPT_CONFIG.get(provider or 'qwen', PROMPT_CONFIG['qwen'])
    # 格式化提示词
    prompt = prompt_template.format(title=title, content=content[:2000])
    
    # 按优先级尝试不同的API（排序：豆包>deepseek>通义千问）
    providers = [provider] if provider else ['doubao', 'deepseek', 'qwen']
    
    for api_provider in providers:
        try:
            if api_provider == 'qwen':
                result = await generate_with_qwen(title, content, prompt)
                if result:
                    logger.info(f"使用通义千问API生成SEO内容成功")
                    return result
            elif api_provider == 'deepseek':
                result = await generate_with_deepseek(title, content, prompt)
                if result:
                    logger.info(f"使用DeepSeek API生成SEO内容成功")
                    return result
            elif api_provider == 'doubao':
                result = await generate_with_doubao(title, content, prompt)
                if result:
                    logger.info(f"使用豆包API生成SEO内容成功")
                    return result
        except Exception as e:
            logger.warning(f"{api_provider} API调用失败: {e}，尝试下一个API")
            continue
    
    # 所有API都失败，使用模拟数据
    logger.warning("所有AI API调用失败，使用模拟数据")
    return generate_mock_seo_content(title, content)

async def generate_with_qwen(title: str, content: str, prompt: str) -> dict:
    """使用通义千问（阿里云）API生成SEO内容"""
    try:
        import dashscope
        api_key = os.getenv('DASHSCOPE_API_KEY', '')
        if not api_key:
            logger.warning("通义千问API密钥未配置")
            return None
        
        dashscope.api_key = api_key
        
        from dashscope import Generation
        
        response = Generation.call(
            model='qwen-turbo',  # 或 'qwen-plus' 更高质量但更贵
            messages=[
                {'role': 'system', 'content': '你是一个专业的SEO内容生成助手，擅长生成高质量的摘要、关键词和URL友好的slug。'},
                {'role': 'user', 'content': prompt}
            ],
            temperature=0.7,
            result_format='message'
        )
        
        if response.status_code == 200:
            result_text = response.output.choices[0].message.content
            logger.info(f"通义千问API调用成功，返回内容长度: {len(result_text)}")
            return parse_ai_response(result_text)
        else:
            logger.error(f"通义千问API错误: {response.message}")
            return None
    except ImportError:
        logger.warning("未安装dashscope库，跳过通义千问API")
        return None
    except Exception as e:
        logger.error(f"通义千问API调用异常: {e}")
        import traceback
        logger.error(f"通义千问API错误详情: {traceback.format_exc()}")
        return None

async def generate_with_ernie(title: str, content: str, prompt: str) -> dict:
    """使用文心一言（百度）API生成SEO内容"""
    try:
        import qianfan
        api_key = os.getenv('QIANFAN_API_KEY', '')
        secret_key = os.getenv('QIANFAN_SECRET_KEY', '')
        if not api_key or not secret_key:
            return None
        
        chat_comp = qianfan.ChatCompletion(ak=api_key, sk=secret_key)
        
        response = chat_comp.do(
            model="ERNIE-Bot-turbo",  # 或 "ERNIE-Bot" 更高质量
            messages=[
                {'role': 'user', 'content': prompt}
            ],
            temperature=0.7
        )
        
        if 'result' in response:
            result_text = response['result']
            return parse_ai_response(result_text)
        else:
            logger.error(f"文心一言API错误: {response}")
            return None
    except ImportError:
        logger.warning("未安装qianfan库，跳过文心一言API")
        return None
    except Exception as e:
        logger.error(f"文心一言API调用异常: {e}")
        return None

async def generate_with_deepseek(title: str, content: str, prompt: str) -> dict:
    """使用DeepSeek API生成SEO内容（使用requests直接调用，避免openai库版本问题）"""
    try:
        import requests
        api_key = os.getenv('DEEPSEEK_API_KEY', '')
        if not api_key:
            logger.warning("DeepSeek API密钥未配置")
            return None
        
        # 根据DeepSeek官方文档，使用requests直接调用API
        url = "https://api.deepseek.com/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        data = {
            "model": "deepseek-chat",  # 使用deepseek-chat模型（对应DeepSeek-V3.2非思考模式）
            "messages": [
                {"role": "system", "content": "你是一个专业的SEO内容生成助手，擅长生成高质量的摘要、关键词和URL友好的slug。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "stream": False
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            
            # 获取返回内容
            if 'choices' in result and len(result['choices']) > 0:
                result_text = result['choices'][0]['message']['content']
                
                # 记录token使用情况
                if 'usage' in result:
                    usage = result['usage']
                    prompt_tokens = usage.get('prompt_tokens', 0)
                    completion_tokens = usage.get('completion_tokens', 0)
                    total_tokens = usage.get('total_tokens', 0)
                    logger.info(f"DeepSeek API调用成功 - 模型: deepseek-chat, 输入Token: {prompt_tokens}, 输出Token: {completion_tokens}, 总计Token: {total_tokens}")
                else:
                    logger.info(f"DeepSeek API调用成功，返回内容长度: {len(result_text)}")
                
                return parse_ai_response(result_text)
            else:
                logger.error("DeepSeek API响应格式异常：没有choices字段")
                return None
        else:
            # 处理错误
            try:
                error_data = response.json()
                if 'error' in error_data:
                    error_info = error_data['error']
                    error_code = error_info.get('code', '未知')
                    error_message = error_info.get('message', '未知错误')
                    logger.error(f"DeepSeek API错误 - HTTP状态码: {response.status_code}, 错误码: {error_code}, 错误消息: {error_message}")
                else:
                    logger.error(f"DeepSeek API错误 - HTTP状态码: {response.status_code}, 响应: {error_data}")
            except:
                logger.error(f"DeepSeek API错误 - HTTP状态码: {response.status_code}, 响应: {response.text}")
            return None
            
    except ImportError:
        logger.warning("未安装requests库，跳过DeepSeek API")
        return None
    except Exception as e:
        logger.error(f"DeepSeek API调用异常: {e}")
        import traceback
        logger.error(f"DeepSeek API错误详情: {traceback.format_exc()}")
        return None

async def generate_with_doubao(title: str, content: str, prompt: str) -> dict:
    """使用豆包（字节跳动）API生成SEO内容（使用requests直接调用，避免openai库版本问题）"""
    try:
        import requests
        api_key = os.getenv('DOUBAO_API_KEY', '')
        if not api_key:
            logger.warning("豆包API密钥未配置")
            return None
        
        # 豆包使用OpenAI兼容接口，通过火山引擎访问
        # 根据火山引擎文档，使用requests直接调用API
        url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        # 模型名称需要从火山引擎控制台获取实际的模型端点ID
        model_name = os.getenv('DOUBAO_MODEL', 'ep-20251214170039-ml795')
        
        data = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "你是一个专业的SEO内容生成助手，擅长生成高质量的摘要、关键词和URL友好的slug。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "stream": False
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            
            # 获取返回内容
            if 'choices' in result and len(result['choices']) > 0:
                result_text = result['choices'][0]['message']['content']
                
                # 记录token使用情况
                if 'usage' in result:
                    usage = result['usage']
                    prompt_tokens = usage.get('prompt_tokens', 0)
                    completion_tokens = usage.get('completion_tokens', 0)
                    total_tokens = usage.get('total_tokens', 0)
                    logger.info(f"豆包API调用成功 - 模型: {model_name}, 输入Token: {prompt_tokens}, 输出Token: {completion_tokens}, 总计Token: {total_tokens}")
                else:
                    logger.info(f"豆包API调用成功 - 模型: {model_name}, 返回内容长度: {len(result_text)}")
                
                return parse_ai_response(result_text)
            else:
                logger.error("豆包API响应格式异常：没有choices字段")
                return None
        else:
            # 处理错误
            try:
                error_data = response.json()
                if 'error' in error_data:
                    error_info = error_data['error']
                    error_code = error_info.get('code', '未知')
                    error_message = error_info.get('message', '未知错误')
                    logger.error(f"豆包API错误 - HTTP状态码: {response.status_code}, 错误码: {error_code}, 错误消息: {error_message}")
                else:
                    logger.error(f"豆包API错误 - HTTP状态码: {response.status_code}, 响应: {error_data}")
            except:
                logger.error(f"豆包API错误 - HTTP状态码: {response.status_code}, 响应: {response.text}")
            return None
            
    except ImportError:
        logger.warning("未安装requests库，跳过豆包API")
        return None
    except Exception as e:
        logger.error(f"豆包API调用异常: {e}")
        import traceback
        logger.error(f"豆包API错误详情: {traceback.format_exc()}")
        return None

def parse_ai_response(result_text: str) -> dict:
    """解析AI返回的JSON格式响应"""
    import json
    import re
    
    try:
        # 尝试直接解析JSON
        result = json.loads(result_text)
        return {
            'summary': result.get('summary', '').strip(),
            'keywords': result.get('keywords', '').strip(),
            'slug': result.get('slug', '').strip()
        }
    except json.JSONDecodeError:
        # 如果直接解析失败，尝试提取JSON部分
        try:
            # 查找JSON对象
            json_match = re.search(r'\{[^{}]*"summary"[^{}]*\}', result_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return {
                    'summary': result.get('summary', '').strip(),
                    'keywords': result.get('keywords', '').strip(),
                    'slug': result.get('slug', '').strip()
                }
        except:
            pass
        
        # 如果还是失败，尝试从文本中提取
        logger.warning("AI返回格式不是标准JSON，尝试提取信息")
        summary_match = re.search(r'"summary"\s*:\s*"([^"]+)"', result_text)
        keywords_match = re.search(r'"keywords"\s*:\s*"([^"]+)"', result_text)
        slug_match = re.search(r'"slug"\s*:\s*"([^"]+)"', result_text)
        
        return {
            'summary': summary_match.group(1) if summary_match else '',
            'keywords': keywords_match.group(1) if keywords_match else '',
            'slug': slug_match.group(1) if slug_match else ''
        }

def generate_mock_seo_content(title: str, content: str) -> dict:
    """生成模拟的SEO内容（用于测试）"""
    # 生成摘要（截取前68字）
    summary = content[:68] if len(content) > 68 else content
    if len(content) > 68:
        summary = summary[:65] + "..."
    
    # 生成关键词（从标题和内容中提取）
    keywords = extract_keywords(title, content)
    
    # 生成slug
    slug = generate_slug(title)
    
    return {
        'summary': summary,
        'keywords': keywords,
        'slug': slug
    }

def extract_keywords(title: str, content: str) -> str:
    """从标题和内容中提取关键词"""
    # 简单的关键词提取逻辑（实际应该使用更复杂的NLP方法）
    words = (title + " " + content[:500]).lower()
    # 移除标点符号
    words = re.sub(r'[^\w\s]', ' ', words)
    # 常见的中文停用词（简化版）
    stop_words = {'的', '是', '在', '了', '和', '有', '为', '与', '等', '及', '或', '但', '而', '也', '都', '就', '要', '可以', '这个', '那个'}
    word_list = [w for w in words.split() if w and len(w) > 1 and w not in stop_words]
    # 取前3-6个
    keywords = word_list[:6] if len(word_list) >= 6 else word_list[:3] if len(word_list) >= 3 else ['关键词1', '关键词2', '关键词3']
    return ','.join(keywords[:6])

def generate_slug(title: str) -> str:
    """根据标题生成slug"""
    # 转换为小写
    slug = title.lower()
    # 移除特殊字符，只保留字母、数字和空格
    slug = re.sub(r'[^\w\s-]', '', slug)
    # 将空格和多个连字符替换为单个连字符
    slug = re.sub(r'[\s_-]+', '-', slug)
    # 移除首尾的连字符
    slug = slug.strip('-')
    # 如果为空，使用默认值
    if not slug:
        slug = 'article-' + str(uuid.uuid4())[:8]
    return slug[:50]  # 限制长度

def read_docx(file_path: str) -> dict:
    """读取Word文档，提取标题和内容"""
    try:
        doc = Document(file_path)
        title = ""
        content_parts = []
        
        # 提取标题（通常是第一个段落或第一个标题样式）
        for para in doc.paragraphs:
            if para.style.name.startswith('Heading') or not title:
                if para.text.strip():
                    if not title:
                        title = para.text.strip()
                    else:
                        content_parts.append(para.text.strip())
            else:
                content_parts.append(para.text.strip())
        
        # 如果没有找到标题，使用第一个段落
        if not title and content_parts:
            title = content_parts[0]
            content_parts = content_parts[1:]
        
        content = '\n'.join(content_parts)
        
        return {
            'title': title or '未命名文档',
            'content': content or '文档内容为空'
        }
    except Exception as e:
        logger.error(f"读取Word文档失败: {e}")
        raise HTTPException(status_code=400, detail=f"读取Word文档失败: {str(e)}")

@app.get("/", response_class=HTMLResponse)
async def read_root():
    """主页面"""
    html_content = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TISI 文章助手工具</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        .header {
            text-align: center;
            color: white;
            margin-bottom: 30px;
        }
        .header h1 { font-size: 2.5em; margin-bottom: 10px; }
        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            justify-content: center;
        }
        .tab {
            padding: 12px 24px;
            background: rgba(255, 255, 255, 0.2);
            color: white;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 16px;
            transition: all 0.3s;
        }
        .tab.active {
            background: white;
            color: #667eea;
        }
        .tab-content {
            display: none;
            background: white;
            border-radius: 12px;
            padding: 30px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        }
        .tab-content.active {
            display: block;
        }
        .upload-area {
            border: 2px dashed #667eea;
            border-radius: 8px;
            padding: 40px;
            text-align: center;
            margin-bottom: 20px;
            transition: all 0.3s;
        }
        .upload-area:hover {
            border-color: #764ba2;
            background: #f8f9fa;
        }
        .upload-area.dragover {
            border-color: #764ba2;
            background: #e9ecef;
        }
        input[type="file"] {
            margin: 10px 0;
        }
        button {
            background: #667eea;
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 16px;
            margin: 5px;
            transition: all 0.3s;
        }
        button:hover {
            background: #764ba2;
            transform: translateY(-2px);
        }
        .result {
            margin-top: 20px;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 8px;
        }
        .result-item {
            margin: 15px 0;
        }
        .result-item label {
            font-weight: bold;
            color: #667eea;
            display: block;
            margin-bottom: 5px;
        }
        .result-item div {
            padding: 10px;
            background: white;
            border-radius: 4px;
            border-left: 4px solid #667eea;
        }
        .history-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }
        .history-table th,
        .history-table td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }
        .history-table th {
            background: #667eea;
            color: white;
        }
        .history-table tr:hover {
            background: #f8f9fa;
        }
        .image-preview {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }
        .image-item {
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 10px;
            text-align: center;
        }
        .image-item img {
            max-width: 100%;
            height: auto;
            border-radius: 4px;
        }
        .loading {
            text-align: center;
            padding: 20px;
            color: #667eea;
        }
    </style>
</head>
<body>
    <!-- 登录弹窗 -->
    <div id="loginOverlay" class="login-overlay">
        <div class="login-box">
            <h2>🔐 用户登录</h2>
            <div id="loginError" class="login-error">用户名或密码错误</div>
            <input type="text" id="loginUsername" placeholder="用户名" autocomplete="username">
            <input type="password" id="loginPassword" placeholder="密码" autocomplete="current-password">
            <button onclick="handleLogin()" style="width: 100%; padding: 12px; background: #667eea; color: white; border: none; border-radius: 6px; font-size: 16px; cursor: pointer;">登录</button>
            <div style="margin-top: 15px; text-align: center; font-size: 12px; color: #666;">
                💡 未登录用户只能查看界面，无法使用功能
            </div>
        </div>
    </div>
    
    <!-- 功能禁用遮罩 -->
    <div id="disabledOverlay" class="disabled-overlay">
        <div class="disabled-message">
            <h2 style="color: #667eea; margin-bottom: 15px;">🔒 需要登录</h2>
            <p style="margin-bottom: 20px;">此功能需要登录后才能使用</p>
            <button onclick="showLogin()" style="padding: 12px 24px; background: #667eea; color: white; border: none; border-radius: 6px; font-size: 16px; cursor: pointer;">立即登录</button>
        </div>
    </div>
    
    <div class="container" style="position: relative;">
        <div class="header">
            <h1>🚀 TISI 文章助手工具</h1>
            <p>SEO助手 | 图片转换工具</p>
            <div id="authStatus" style="margin-top: 15px;">
                <span id="authInfo" style="background: rgba(255,255,255,0.2); padding: 8px 16px; border-radius: 6px; font-size: 14px;"></span>
                <button id="logoutBtn" onclick="handleLogout()" style="margin-left: 10px; padding: 8px 16px; background: rgba(255,255,255,0.3); color: white; border: none; border-radius: 6px; cursor: pointer; display: none;">登出</button>
            </div>
        </div>
        
        <div class="tabs">
            <button class="tab active" onclick="switchTab('seo')">SEO助手</button>
            <button class="tab" onclick="switchTab('image')">图片转换</button>
            <button class="tab" onclick="switchTab('history')">历史记录</button>
            <button class="tab" onclick="switchTab('prompt')">提示词</button>
        </div>
        
        <!-- SEO助手 -->
        <div id="seo" class="tab-content active">
            <h2>📝 SEO助手</h2>
            <div style="margin-bottom: 20px; padding: 15px; background: #f8f9fa; border-radius: 8px;">
                <label for="aiProvider" style="display: block; margin-bottom: 8px; font-weight: bold; color: #667eea;">
                    🤖 选择AI模型（可比较生成质量）：
                </label>
                <select id="aiProvider" style="padding: 8px 12px; border: 2px solid #667eea; border-radius: 6px; font-size: 14px; width: 100%; max-width: 400px;">
                    <option value="doubao">豆包（字节跳动）- 推荐，每天200w tokens</option>
                    <option value="deepseek">DeepSeek - 需要付费，质量优秀</option>
                    <option value="qwen">通义千问（阿里云）- 每月200w tokens</option>
                </select>
                <div style="margin-top: 10px; font-size: 12px; color: #666;">
                    💡 提示：可以切换不同模型比较生成质量，选择最适合的模型
                </div>
            </div>
            <div class="upload-area" id="seoUploadArea">
                <p>📄 拖拽Word文档到此处或点击选择文件</p>
                <input type="file" id="seoFileInput" accept=".doc,.docx" multiple>
            </div>
            <button onclick="processSEO()">生成SEO内容</button>
            <div id="seoResults"></div>
        </div>
        
        <!-- 图片转换 -->
        <div id="image" class="tab-content">
            <h2>🖼️ 图片转换工具</h2>
            <div class="upload-area" id="imageUploadArea">
                <p>📷 拖拽WebP图片到此处或点击选择文件（最多20张）</p>
                <input type="file" id="imageFileInput" accept=".webp" multiple>
            </div>
            <button onclick="convertImages()">转换图片</button>
            <div style="margin-top: 15px; padding: 10px; background: #e7f3ff; border-radius: 6px; font-size: 14px; color: #0066cc;">
                💡 <strong>下载提示：</strong>点击"下载"按钮时，浏览器会弹出保存对话框，您可以选择保存路径和文件名。
                <br>现代浏览器（Chrome、Edge等）支持直接选择保存位置。
            </div>
            <div id="imageResults"></div>
        </div>
        
        <!-- 历史记录 -->
        <div id="history" class="tab-content">
            <h2>📊 历史记录</h2>
            <button onclick="loadHistory()">刷新历史记录</button>
            <button onclick="downloadHistory()">下载CSV文件</button>
            <button onclick="deleteHistory()" style="background: #dc3545;">删除历史记录</button>
            <div id="historyContent"></div>
        </div>
        
        <!-- 提示词管理 -->
        <div id="prompt" class="tab-content">
            <h2>⚙️ 提示词管理</h2>
            <div id="promptLogin" style="padding: 20px; background: #f8f9fa; border-radius: 8px; max-width: 400px; margin: 20px auto;">
                <p style="margin-bottom: 15px; font-weight: bold;">请输入密码访问提示词设置：</p>
                <input type="password" id="promptPassword" placeholder="请输入密码" style="width: 100%; padding: 10px; margin-bottom: 10px; border: 2px solid #667eea; border-radius: 6px; font-size: 14px;">
                <button onclick="checkPromptPassword()" style="width: 100%; padding: 12px; background: #667eea; color: white; border: none; border-radius: 6px; font-size: 16px; cursor: pointer;">确认</button>
                <div id="promptError" style="color: red; margin-top: 10px; display: none;">密码错误，请重试</div>
            </div>
            <div id="promptContent" style="display: none;">
                <div style="margin-bottom: 20px;">
                    <label style="display: block; margin-bottom: 8px; font-weight: bold;">选择模型：</label>
                    <select id="promptModel" style="padding: 8px 12px; border: 2px solid #667eea; border-radius: 6px; font-size: 14px; width: 100%; max-width: 300px;" onchange="loadPrompt()">
                        <option value="doubao">豆包</option>
                        <option value="deepseek">DeepSeek</option>
                        <option value="qwen">通义千问</option>
                    </select>
                </div>
                <div style="margin-bottom: 20px;">
                    <label style="display: block; margin-bottom: 8px; font-weight: bold;">提示词内容：</label>
                    <textarea id="promptText" rows="20" style="width: 100%; padding: 12px; border: 2px solid #667eea; border-radius: 6px; font-size: 14px; font-family: monospace;" placeholder="提示词内容..."></textarea>
                    <div style="margin-top: 10px; font-size: 12px; color: #666;">
                        💡 提示：使用 {title} 和 {content} 作为占位符，系统会自动替换为实际的文章标题和内容
                    </div>
                </div>
                <button onclick="savePrompt()" style="padding: 12px 24px; background: #28a745; color: white; border: none; border-radius: 6px; font-size: 16px; cursor: pointer; margin-right: 10px;">保存提示词</button>
                <button onclick="resetPrompt()" style="padding: 12px 24px; background: #ffc107; color: #333; border: none; border-radius: 6px; font-size: 16px; cursor: pointer;">重置为默认</button>
                <div id="promptSaveStatus" style="margin-top: 15px;"></div>
            </div>
        </div>
    </div>
    
    <script>
        // 认证状态
        let isAuthenticated = false;
        
        // 页面加载时检查认证状态
        async function checkAuthStatus() {
            try {
                const response = await fetch('/api/auth/check', {
                    method: 'POST',
                    credentials: 'include'
                });
                const result = await response.json();
                isAuthenticated = result.authenticated || false;
                
                if (!isAuthenticated) {
                    // 显示登录提示
                    showLogin();
                }
            } catch (error) {
                console.error('检查认证状态失败:', error);
                showLogin();
            }
        }
        
        // 显示登录弹窗
        function showLogin() {
            document.getElementById('loginOverlay').classList.add('active');
        }
        
        // 隐藏登录弹窗
        function hideLogin() {
            document.getElementById('loginOverlay').classList.remove('active');
            document.getElementById('loginError').style.display = 'none';
            document.getElementById('loginUsername').value = '';
            document.getElementById('loginPassword').value = '';
        }
        
        // 处理登录
        async function handleLogin() {
            const username = document.getElementById('loginUsername').value;
            const password = document.getElementById('loginPassword').value;
            
            if (!username || !password) {
                document.getElementById('loginError').textContent = '请输入用户名和密码';
                document.getElementById('loginError').style.display = 'block';
                return;
            }
            
            try {
                const formData = new FormData();
                formData.append('username', username);
                formData.append('password', password);
                
                const response = await fetch('/api/auth/login', {
                    method: 'POST',
                    body: formData,
                    credentials: 'include'
                });
                
                const result = await response.json();
                
                if (response.ok && result.authenticated) {
                    isAuthenticated = true;
                    hideLogin();
                    updateAuthStatus();
                    // 刷新页面以启用所有功能
                    location.reload();
                } else {
                    document.getElementById('loginError').textContent = '用户名或密码错误';
                    document.getElementById('loginError').style.display = 'block';
                }
            } catch (error) {
                document.getElementById('loginError').textContent = '登录失败，请重试';
                document.getElementById('loginError').style.display = 'block';
            }
        }
        
        // 处理登出
        async function handleLogout() {
            try {
                await fetch('/api/auth/logout', {
                    method: 'POST',
                    credentials: 'include'
                });
                isAuthenticated = false;
                location.reload();
            } catch (error) {
                console.error('登出失败:', error);
            }
        }
        
        // 检查功能权限
        function checkAuthBeforeAction(action) {
            if (!isAuthenticated) {
                document.getElementById('disabledOverlay').classList.add('active');
                return false;
            }
            return true;
        }
        
        // 更新认证状态显示
        function updateAuthStatus() {
            const authInfo = document.getElementById('authInfo');
            const logoutBtn = document.getElementById('logoutBtn');
            if (isAuthenticated) {
                authInfo.textContent = '✓ 已登录';
                authInfo.style.background = 'rgba(40, 167, 69, 0.3)';
                logoutBtn.style.display = 'inline-block';
            } else {
                authInfo.textContent = '⚠ 未登录（仅可查看）';
                authInfo.style.background = 'rgba(255, 193, 7, 0.3)';
                logoutBtn.style.display = 'none';
            }
        }
        
        // 页面加载时检查认证
        window.addEventListener('DOMContentLoaded', async function() {
            await checkAuthStatus();
            updateAuthStatus();
        });
        
        // 点击遮罩关闭
        document.getElementById('loginOverlay').addEventListener('click', function(e) {
            if (e.target === this) {
                hideLogin();
            }
        });
        
        document.getElementById('disabledOverlay').addEventListener('click', function(e) {
            if (e.target === this) {
                this.classList.remove('active');
            }
        });
        
        // 回车键登录
        document.getElementById('loginPassword').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                handleLogin();
            }
        });
        
        function switchTab(tabName) {
            // 隐藏所有标签页内容
            document.querySelectorAll('.tab-content').forEach(tab => {
                tab.classList.remove('active');
            });
            // 移除所有标签按钮的active类
            document.querySelectorAll('.tab').forEach(btn => {
                btn.classList.remove('active');
            });
            // 显示选中的标签页
            document.getElementById(tabName).classList.add('active');
            // 激活对应的标签按钮
            event.target.classList.add('active');
            
            if (tabName === 'history') {
                loadHistory();
            }
        }
        
        // SEO处理
        async function processSEO() {
            if (!checkAuthBeforeAction('processSEO')) return;
            
            const fileInput = document.getElementById('seoFileInput');
            const files = fileInput.files;
            const providerSelect = document.getElementById('aiProvider');
            const selectedProvider = providerSelect.value;
            
            if (files.length === 0) {
                alert('请选择Word文档');
                return;
            }
            
            const resultsDiv = document.getElementById('seoResults');
            const providerName = providerSelect.options[providerSelect.selectedIndex].text.split('（')[0];
            resultsDiv.innerHTML = `<div class="loading">处理中...（使用${providerName}）</div>`;
            
            let processedCount = 0;
            const totalFiles = files.length;
            
            for (let file of files) {
                const formData = new FormData();
                formData.append('file', file);
                formData.append('provider', selectedProvider);
                
                try {
                    const response = await fetch('/api/seo/process', {
                        method: 'POST',
                        body: formData
                    });
                    
                    const result = await response.json();
                    
                    if (response.ok) {
                        processedCount++;
                        // 如果是第一个结果，替换"处理中..."
                        if (processedCount === 1) {
                            resultsDiv.innerHTML = '';
                        }
                        
                        const resultId = 'result_' + Date.now() + '_' + processedCount;
                        resultsDiv.innerHTML += `
                            <div class="result" id="${resultId}">
                                <div style="margin-bottom: 10px; padding: 8px; background: #e7f3ff; border-radius: 4px; font-size: 12px; color: #0066cc;">
                                    🤖 使用模型: ${providerName}
                                </div>
                                <div class="result-item">
                                    <label>标题：</label>
                                    <div>${result.title}</div>
                                </div>
                                <div class="result-item">
                                    <label>摘要：</label>
                                    <div>${result.summary}</div>
                                </div>
                                <div class="result-item">
                                    <label>关键词：</label>
                                    <div>${result.keywords}</div>
                                </div>
                                <div class="result-item">
                                    <label>Slug：</label>
                                    <div>${result.slug}</div>
                                </div>
                                <div class="result-item" style="margin-top: 15px; padding-top: 15px; border-top: 1px solid #ddd;">
                                    <label>生成结果评分（可选）：</label>
                                    <div style="display: flex; align-items: center; gap: 10px; margin-top: 8px;">
                                        <button onclick="rateResult('${resultId}', '${selectedProvider}', '${result.title.replace(/'/g, "\\'")}', '${result.summary.replace(/'/g, "\\'")}', '${result.keywords.replace(/'/g, "\\'")}', '${result.slug.replace(/'/g, "\\'")}', 1)" style="padding: 5px 10px; font-size: 14px; background: #f0f0f0; border: 1px solid #ccc; cursor: pointer;">1分</button>
                                        <button onclick="rateResult('${resultId}', '${selectedProvider}', '${result.title.replace(/'/g, "\\'")}', '${result.summary.replace(/'/g, "\\'")}', '${result.keywords.replace(/'/g, "\\'")}', '${result.slug.replace(/'/g, "\\'")}', 2)" style="padding: 5px 10px; font-size: 14px; background: #f0f0f0; border: 1px solid #ccc; cursor: pointer;">2分</button>
                                        <button onclick="rateResult('${resultId}', '${selectedProvider}', '${result.title.replace(/'/g, "\\'")}', '${result.summary.replace(/'/g, "\\'")}', '${result.keywords.replace(/'/g, "\\'")}', '${result.slug.replace(/'/g, "\\'")}', 3)" style="padding: 5px 10px; font-size: 14px; background: #f0f0f0; border: 1px solid #ccc; cursor: pointer;">3分</button>
                                        <button onclick="rateResult('${resultId}', '${selectedProvider}', '${result.title.replace(/'/g, "\\'")}', '${result.summary.replace(/'/g, "\\'")}', '${result.keywords.replace(/'/g, "\\'")}', '${result.slug.replace(/'/g, "\\'")}', 4)" style="padding: 5px 10px; font-size: 14px; background: #f0f0f0; border: 1px solid #ccc; cursor: pointer;">4分</button>
                                        <button onclick="rateResult('${resultId}', '${selectedProvider}', '${result.title.replace(/'/g, "\\'")}', '${result.summary.replace(/'/g, "\\'")}', '${result.keywords.replace(/'/g, "\\'")}', '${result.slug.replace(/'/g, "\\'")}', 5)" style="padding: 5px 10px; font-size: 14px; background: #f0f0f0; border: 1px solid #ccc; cursor: pointer;">5分</button>
                                        <span id="${resultId}_rating" style="margin-left: 10px; color: #28a745; font-weight: bold;"></span>
                                    </div>
                                </div>
                            </div>
                        `;
                    } else {
                        if (processedCount === 0) {
                            resultsDiv.innerHTML = '';
                        }
                        resultsDiv.innerHTML += `<div class="result" style="color: red;">错误: ${result.detail}</div>`;
                    }
                } catch (error) {
                    if (processedCount === 0) {
                        resultsDiv.innerHTML = '';
                    }
                    resultsDiv.innerHTML += `<div class="result" style="color: red;">错误: ${error.message}</div>`;
                }
            }
            
            // 所有文件处理完成后，显示"已完成"状态
            if (processedCount > 0) {
                resultsDiv.innerHTML += '<div class="loading" style="color: #28a745; margin-top: 20px;">✓ 已完成</div>';
            }
        }
        
        // 图片转换
        async function convertImages() {
            if (!checkAuthBeforeAction('convertImages')) return;
            
            const fileInput = document.getElementById('imageFileInput');
            const files = fileInput.files;
            
            if (files.length === 0) {
                alert('请选择WebP图片');
                return;
            }
            
            if (files.length > 20) {
                alert('最多只能上传20张图片');
                return;
            }
            
            const resultsDiv = document.getElementById('imageResults');
            resultsDiv.innerHTML = '<div class="loading">转换中...</div>';
            
            const formData = new FormData();
            for (let file of files) {
                formData.append('files', file);
            }
            
            try {
                const response = await fetch('/api/image/convert', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    // 保存文件列表到全局变量，供批量下载使用
                    window.convertedImages = result.files.map(file => {
                        let downloadName = file.download_name;
                        if (!downloadName && file.original_name) {
                            // 将 .webp 替换为 .png
                            downloadName = file.original_name.replace(/\.webp$/i, '.png');
                        }
                        return {
                            filename: file.filename,
                            original_name: file.original_name,
                            download_name: downloadName || file.filename
                        };
                    });
                    
                    let html = '<div class="image-preview">';
                    window.convertedImages.forEach((file, index) => {
                        html += `
                            <div class="image-item">
                                <img src="/api/image/download/${file.filename}?original_name=${encodeURIComponent(file.original_name)}" alt="${file.original_name}">
                                <p>${file.original_name}</p>
                                <button onclick="downloadImage('${file.filename}', '${file.download_name}')">下载</button>
                            </div>
                        `;
                    });
                    html += '</div>';
                    html += '<button onclick="downloadAllImages()">批量下载</button>';
                    resultsDiv.innerHTML = html;
                } else {
                    resultsDiv.innerHTML = `<div class="result" style="color: red;">错误: ${result.detail}</div>`;
                }
            } catch (error) {
                resultsDiv.innerHTML = `<div class="result" style="color: red;">错误: ${error.message}</div>`;
            }
        }
        
        async function downloadImage(filename, downloadName) {
            try {
                // 获取原始文件名（去掉.webp，加上.png）
                const originalName = downloadName || filename;
                const finalFileName = originalName.endsWith('.png') ? originalName : originalName.replace(/\.webp$/i, '.png');
                
                // 获取图片数据
                const response = await fetch(`/api/image/download/${filename}?original_name=${encodeURIComponent(originalName)}`);
                const blob = await response.blob();
                
                // 尝试使用 File System Access API（现代浏览器支持）
                if ('showSaveFilePicker' in window) {
                    try {
                        const fileHandle = await window.showSaveFilePicker({
                            suggestedName: finalFileName,
                            types: [{
                                description: 'PNG图片',
                                accept: { 'image/png': ['.png'] }
                            }]
                        });
                        
                        const writable = await fileHandle.createWritable();
                        await writable.write(blob);
                        await writable.close();
                        
                        alert('图片已保存到: ' + fileHandle.name);
                        return;
                    } catch (error) {
                        // 用户取消了文件选择对话框，不显示错误
                        if (error.name !== 'AbortError') {
                            console.log('File System Access API 失败，使用传统下载方式:', error);
                        } else {
                            return; // 用户取消，直接返回
                        }
                    }
                }
                
                // 回退到传统下载方式（浏览器会弹出保存对话框）
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = finalFileName;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
            } catch (error) {
                alert('下载失败: ' + error.message);
            }
        }
        
        async function downloadAllImages() {
            try {
                // 检查是否有转换后的图片
                if (!window.convertedImages || window.convertedImages.length === 0) {
                    alert('没有可下载的图片');
                    return;
                }
                
                // 尝试使用 File System Access API 让用户选择文件夹
                if ('showDirectoryPicker' in window) {
                    try {
                        const directoryHandle = await window.showDirectoryPicker();
                        
                        // 显示进度提示
                        const totalFiles = window.convertedImages.length;
                        let completed = 0;
                        
                        // 逐个下载并保存到选择的文件夹
                        for (let file of window.convertedImages) {
                            try {
                                const response = await fetch(`/api/image/download/${file.filename}?original_name=${encodeURIComponent(file.original_name)}`);
                                const blob = await response.blob();
                                
                                const finalFileName = file.download_name.endsWith('.png') ? file.download_name : file.download_name.replace(/\.webp$/i, '.png');
                                const fileHandle = await directoryHandle.getFileHandle(finalFileName, { create: true });
                                const writable = await fileHandle.createWritable();
                                await writable.write(blob);
                                await writable.close();
                                
                                completed++;
                            } catch (error) {
                                console.error(`下载 ${file.original_name} 失败:`, error);
                            }
                        }
                        
                        alert(`成功保存 ${completed}/${totalFiles} 张图片到选择的文件夹！`);
                        return;
                    } catch (error) {
                        // 用户取消了文件夹选择对话框
                        if (error.name !== 'AbortError') {
                            console.log('文件夹选择失败，使用ZIP下载方式:', error);
                            // 继续执行ZIP下载
                        } else {
                            return; // 用户取消，直接返回
                        }
                    }
                }
                
                // 回退到ZIP下载方式（浏览器会弹出保存对话框）
                window.open('/api/image/download-all', '_blank');
            } catch (error) {
                alert('批量下载失败: ' + error.message);
            }
        }
        
        // 历史记录
        async function loadHistory() {
            const contentDiv = document.getElementById('historyContent');
            contentDiv.innerHTML = '<div class="loading">加载中...</div>';
            
            try {
                const response = await fetch('/api/history');
                const data = await response.json();
                
                if (data.length === 0) {
                    contentDiv.innerHTML = '<p>暂无历史记录</p>';
                    return;
                }
                
                // 按时间倒序排列（最新的在前）
                data.sort((a, b) => {
                    // 时间格式：YYYY-MM-DD HH:MM:SS
                    const timeA = a[0] || '';
                    const timeB = b[0] || '';
                    return timeB.localeCompare(timeA); // 倒序：B在前，A在后
                });
                
                // 检查是否有AI模型列（兼容旧数据）
                let html = '<table class="history-table"><thead><tr><th>时间</th><th>标题</th><th>摘要</th><th>关键词</th><th>Slug</th><th>文章附加</th><th>AI模型</th></tr></thead><tbody>';
                data.forEach(row => {
                    html += `<tr>
                        <td>${row[0] || ''}</td>
                        <td>${row[1] || ''}</td>
                        <td>${row[2] || ''}</td>
                        <td>${row[3] || ''}</td>
                        <td>${row[4] || ''}</td>
                        <td>${row[5] || ''}</td>
                        <td>${row[6] || '未知'}</td>
                    </tr>`;
                });
                html += '</tbody></table>';
                contentDiv.innerHTML = html;
            } catch (error) {
                contentDiv.innerHTML = `<div style="color: red;">错误: ${error.message}</div>`;
            }
        }
        
        function downloadHistory() {
            window.open('/api/history/download', '_blank');
        }
        
        // 删除历史记录（两次确认）
        async function deleteHistory() {
            // 第一次确认
            if (!confirm('你确认要删除历史记录吗？')) {
                return;
            }
            
            // 第二次确认
            if (!confirm('历史记录将从服务器彻底删除，你确认要删除吗？')) {
                return;
            }
            
            try {
                const response = await fetch('/api/history/delete', {
                    method: 'DELETE'
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    alert('历史记录已删除');
                    loadHistory(); // 刷新显示
                } else {
                    alert('删除失败: ' + result.detail);
                }
            } catch (error) {
                alert('删除失败: ' + error.message);
            }
        }
        
        // 评分功能
        async function rateResult(resultId, provider, title, summary, keywords, slug, rating) {
            try {
                const response = await fetch('/api/seo/rate', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        provider: provider,
                        title: title,
                        summary: summary,
                        keywords: keywords,
                        slug: slug,
                        rating: rating
                    })
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    // 显示评分成功
                    const ratingSpan = document.getElementById(resultId + '_rating');
                    if (ratingSpan) {
                        ratingSpan.textContent = `✓ 已评分：${rating}分`;
                        ratingSpan.style.color = '#28a745';
                    }
                    // 禁用所有评分按钮
                    const resultDiv = document.getElementById(resultId);
                    if (resultDiv) {
                        const buttons = resultDiv.querySelectorAll('button[onclick^="rateResult"]');
                        buttons.forEach(btn => {
                            btn.disabled = true;
                            btn.style.opacity = '0.5';
                            btn.style.cursor = 'not-allowed';
                        });
                    }
                } else {
                    alert('评分失败: ' + result.detail);
                }
            } catch (error) {
                alert('评分失败: ' + error.message);
            }
        }
        
        // 提示词管理
        let promptAuthenticated = false;
        
        async function checkPromptPassword() {
            const password = document.getElementById('promptPassword').value;
            
            try {
                const response = await fetch('/api/prompt/check', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ password: password })
                });
                
                const result = await response.json();
                
                if (response.ok && result.authenticated) {
                    promptAuthenticated = true;
                    document.getElementById('promptLogin').style.display = 'none';
                    document.getElementById('promptContent').style.display = 'block';
                    loadPrompt();
                } else {
                    document.getElementById('promptError').style.display = 'block';
                    document.getElementById('promptPassword').value = '';
                }
            } catch (error) {
                alert('验证失败: ' + error.message);
            }
        }
        
        async function loadPrompt() {
            if (!promptAuthenticated) return;
            
            const model = document.getElementById('promptModel').value;
            
            try {
                const response = await fetch(`/api/prompt/get?model=${model}`);
                const result = await response.json();
                
                if (response.ok) {
                    document.getElementById('promptText').value = result.prompt || '';
                }
            } catch (error) {
                console.error('加载提示词失败:', error);
            }
        }
        
        async function savePrompt() {
            if (!promptAuthenticated) {
                alert('请先验证密码');
                return;
            }
            
            const model = document.getElementById('promptModel').value;
            const prompt = document.getElementById('promptText').value;
            
            try {
                const response = await fetch('/api/prompt/save', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        model: model,
                        prompt: prompt
                    })
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    const statusDiv = document.getElementById('promptSaveStatus');
                    statusDiv.innerHTML = '<div style="color: #28a745; padding: 10px; background: #d4edda; border-radius: 4px;">✓ 提示词已保存成功！</div>';
                    setTimeout(() => {
                        statusDiv.innerHTML = '';
                    }, 3000);
                } else {
                    alert('保存失败: ' + result.detail);
                }
            } catch (error) {
                alert('保存失败: ' + error.message);
            }
        }
        
        async function resetPrompt() {
            if (!confirm('确定要重置为默认提示词吗？')) {
                return;
            }
            
            const model = document.getElementById('promptModel').value;
            
            try {
                const response = await fetch(`/api/prompt/reset?model=${model}`);
                const result = await response.json();
                
                if (response.ok) {
                    document.getElementById('promptText').value = result.prompt || '';
                    const statusDiv = document.getElementById('promptSaveStatus');
                    statusDiv.innerHTML = '<div style="color: #28a745; padding: 10px; background: #d4edda; border-radius: 4px;">✓ 已重置为默认提示词</div>';
                    setTimeout(() => {
                        statusDiv.innerHTML = '';
                    }, 3000);
                }
            } catch (error) {
                alert('重置失败: ' + error.message);
            }
        }
        
        // 切换标签页时检查提示词权限
        const originalSwitchTab = switchTab;
        switchTab = function(tabName) {
            originalSwitchTab(tabName);
            if (tabName === 'prompt' && !promptAuthenticated) {
                document.getElementById('promptLogin').style.display = 'block';
                document.getElementById('promptContent').style.display = 'none';
            }
        };
        
        // 拖拽上传
        ['seoUploadArea', 'imageUploadArea'].forEach(id => {
            const area = document.getElementById(id);
            const input = document.getElementById(id.replace('Area', 'FileInput'));
            
            area.addEventListener('dragover', (e) => {
                e.preventDefault();
                area.classList.add('dragover');
            });
            
            area.addEventListener('dragleave', () => {
                area.classList.remove('dragover');
            });
            
            area.addEventListener('drop', (e) => {
                e.preventDefault();
                area.classList.remove('dragover');
                input.files = e.dataTransfer.files;
            });
        });
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)

@app.post("/api/seo/process")
async def process_seo(file: UploadFile = File(...), provider: str = Form(None)):
    """处理Word文档，生成SEO内容"""
    logger.info(f"收到SEO处理请求: {file.filename}, 使用API: {provider or '默认'}")
    
    # 保存上传的文件
    file_path = f"uploads/{uuid.uuid4()}_{file.filename}"
    async with aiofiles.open(file_path, 'wb') as f:
        content = await file.read()
        await f.write(content)
    
    try:
        # 读取Word文档
        doc_data = read_docx(file_path)
        title = doc_data['title']
        content = doc_data['content']
        
        logger.info(f"文档标题: {title}, 内容长度: {len(content)}")
        
        # 生成SEO内容（传入provider参数）
        seo_data = await generate_seo_content(title, content, provider=provider)
        
        # 确定使用的模型名称
        model_names = {
            'qwen': '通义千问',
            'deepseek': 'DeepSeek',
            'doubao': '豆包'
        }
        used_model = model_names.get(provider or 'qwen', '通义千问')
        
        # 保存到历史记录（增加AI模型字段）
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(HISTORY_CSV, 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                timestamp,
                title,
                seo_data['summary'],
                seo_data['keywords'],
                seo_data['slug'],
                file.filename,
                used_model
            ])
        
        logger.info(f"SEO内容生成成功: {title}, 使用模型: {used_model}")
        
        return {
            'title': title,
            'summary': seo_data['summary'],
            'keywords': seo_data['keywords'],
            'slug': seo_data['slug'],
            'model': used_model
        }
    except Exception as e:
        logger.error(f"处理SEO请求失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # 清理上传的文件（可选）
        if os.path.exists(file_path):
            os.remove(file_path)

@app.post("/api/image/convert")
async def convert_images(files: List[UploadFile] = File(...)):
    """转换WebP图片为PNG"""
    logger.info(f"收到图片转换请求: {len(files)} 张图片")
    
    if len(files) > MAX_WEBP_FILES:
        raise HTTPException(status_code=400, detail=f"最多只能上传{MAX_WEBP_FILES}张图片")
    
    converted_files = []
    
    for file in files:
        if not file.filename.lower().endswith('.webp'):
            continue
        
        try:
            # 读取WebP图片
            image_data = await file.read()
            image = Image.open(io.BytesIO(image_data))
            
            # 转换为PNG
            if image.mode == 'RGBA':
                # 保持透明度
                png_image = image
            else:
                # 转换为RGB
                png_image = image.convert('RGB')
            
            # 保存PNG文件
            filename = f"{uuid.uuid4()}_{file.filename.rsplit('.', 1)[0]}.png"
            output_path = f"outputs/{filename}"
            png_image.save(output_path, 'PNG')
            
            # 保存原始文件名到转换后的文件名映射（用于下载时使用原始文件名）
            converted_files.append({
                'filename': filename,
                'original_name': file.filename,
                'download_name': file.filename.rsplit('.', 1)[0] + '.png'
            })
            
            logger.info(f"图片转换成功: {file.filename} -> {filename}")
        except Exception as e:
            logger.error(f"转换图片失败 {file.filename}: {e}")
            continue
    
    if not converted_files:
        raise HTTPException(status_code=400, detail="没有成功转换的图片")
    
    return {'files': converted_files}

@app.get("/api/image/download/{filename}")
async def download_image(filename: str, original_name: Optional[str] = Query(None)):
    """下载单张转换后的图片"""
    file_path = f"outputs/{filename}"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")
    
    # 如果提供了原始文件名，使用原始文件名（去掉.webp，加上.png）
    if original_name:
        download_filename = original_name.rsplit('.', 1)[0] + '.png'
    else:
        download_filename = filename
    
    return FileResponse(
        file_path,
        media_type='image/png',
        filename=download_filename
    )

@app.get("/api/image/download-all")
async def download_all_images():
    """批量下载所有转换后的图片"""
    output_dir = Path('outputs')
    png_files = list(output_dir.glob('*.png'))
    
    if not png_files:
        raise HTTPException(status_code=404, detail="没有可下载的图片")
    
    # 创建ZIP文件
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for png_file in png_files:
            zip_file.write(png_file, png_file.name)
    
    zip_buffer.seek(0)
    
    return StreamingResponse(
        io.BytesIO(zip_buffer.read()),
        media_type='application/zip',
        headers={'Content-Disposition': 'attachment; filename=converted_images.zip'}
    )

@app.get("/api/history")
async def get_history():
    """获取历史记录"""
    try:
        history_data = []
        if os.path.exists(HISTORY_CSV):
            with open(HISTORY_CSV, 'r', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                next(reader)  # 跳过标题行
                history_data = list(reader)
        
        return history_data
    except Exception as e:
        logger.error(f"读取历史记录失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/history/download")
async def download_history():
    """下载历史记录CSV文件"""
    if not os.path.exists(HISTORY_CSV):
        raise HTTPException(status_code=404, detail="历史记录文件不存在")
    
    return FileResponse(
        HISTORY_CSV,
        media_type='text/csv',
        filename='seo_history.csv'
    )

@app.delete("/api/history/delete")
async def delete_history():
    """删除历史记录CSV文件"""
    try:
        if os.path.exists(HISTORY_CSV):
            os.remove(HISTORY_CSV)
            logger.info("历史记录CSV文件已删除")
            
            # 重新创建空的CSV文件（带标题行，包含AI模型字段）
            with open(HISTORY_CSV, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['时间', '标题', '摘要', '关键词', 'slug', '文章附加', 'AI模型'])
            
            return {'message': '历史记录已删除'}
        else:
            return {'message': '历史记录文件不存在'}
    except Exception as e:
        logger.error(f"删除历史记录失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/seo/rate")
async def rate_seo_result(data: dict):
    """评分SEO生成结果，用于改进模型"""
    try:
        provider = data.get('provider', '')
        title = data.get('title', '')
        summary = data.get('summary', '')
        keywords = data.get('keywords', '')
        slug = data.get('slug', '')
        rating = data.get('rating', 0)
        
        if not provider or not title or rating < 1 or rating > 5:
            raise HTTPException(status_code=400, detail="无效的评分数据")
        
        # 记录评分到日志（包含完整信息，可用于后续分析）
        logger.info(f"收到评分 - 模型: {provider}, 标题: {title}, 评分: {rating}分, 摘要: {summary[:50]}..., 关键词: {keywords}, Slug: {slug}")
        
        # 可以将评分保存到文件，用于后续分析和模型改进
        rating_file = 'history/ratings.csv'
        rating_exists = Path(rating_file).exists()
        
        with open(rating_file, 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            if not rating_exists:
                writer.writerow(['时间', '模型', '标题', '摘要', '关键词', 'Slug', '评分'])
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                provider,
                title,
                summary,
                keywords,
                slug,
                rating
            ])
        
        logger.info(f"评分已保存到: {rating_file}")
        
        return {'message': f'评分已记录：{rating}分，将用于改进模型生成效果', 'rating': rating}
    except Exception as e:
        logger.error(f"记录评分失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/prompt/check")
async def check_prompt_password(data: dict):
    """验证提示词管理密码"""
    password = data.get('password', '')
    if password == PROMPT_PASSWORD:
        return {'authenticated': True}
    else:
        return {'authenticated': False}

@app.get("/api/prompt/get")
async def get_prompt(model: str = Query(...)):
    """获取指定模型的提示词"""
    if model not in PROMPT_CONFIG:
        raise HTTPException(status_code=400, detail="无效的模型名称")
    
    return {'prompt': PROMPT_CONFIG[model]}

@app.post("/api/prompt/save")
async def save_prompt(data: dict):
    """保存提示词"""
    model = data.get('model', '')
    prompt = data.get('prompt', '')
    
    if model not in PROMPT_CONFIG:
        raise HTTPException(status_code=400, detail="无效的模型名称")
    
    if not prompt:
        raise HTTPException(status_code=400, detail="提示词不能为空")
    
    # 更新提示词配置
    PROMPT_CONFIG[model] = prompt
    logger.info(f"提示词已更新 - 模型: {model}")
    
    return {'message': '提示词已保存', 'model': model}

@app.get("/api/prompt/reset")
async def reset_prompt(model: str = Query(...)):
    """重置提示词为默认值"""
    if model not in PROMPT_CONFIG:
        raise HTTPException(status_code=400, detail="无效的模型名称")
    
    # 恢复默认提示词
    default_prompts = {
        'qwen': """你是一个专业的SEO内容优化专家。请根据以下文章内容，生成高质量的SEO信息。

【文章标题】
{title}

【文章内容】
{content}

【任务要求】
请仔细阅读文章标题和内容，理解文章的核心主题和关键信息，然后生成以下SEO内容：

1. **摘要（summary）**：
   - 生成一段简洁、准确、吸引人的中文摘要
   - 必须准确概括文章的核心内容和主要观点
   - 字数严格控制在68字以内（包括标点符号）
   - 语言要流畅自然，具有吸引力
   - 不要使用"本文"、"文章"等词开头

2. **关键词（keywords）**：
   - 根据文章标题、内容和摘要，提取3-6个最相关的关键词
   - 关键词要符合Google SEO规范，具有搜索价值
   - 优先选择用户可能搜索的核心词汇
   - 使用英文逗号,隔开，不要有空格
   - 格式示例：关键词1,关键词2,关键词3

3. **Slug（slug）**：
   - 根据文章的标题和核心内容，生成一个适用于URL的英文slug
   - 全部使用小写字母
   - 只包含字母、数字和连字符（-）
   - 长度控制在30-50个字符之间
   - 要简洁、有意义、易于理解
   - 格式示例：article-title-seo-friendly

【输出格式】
请严格按照以下JSON格式返回，不要添加任何其他文字说明：
{{
    "summary": "这里填写68字以内的中文摘要",
    "keywords": "关键词1,关键词2,关键词3",
    "slug": "article-slug-format"
}}

请开始生成：""",
        'deepseek': """你是一个专业的SEO内容优化专家。请根据以下文章内容，生成高质量的SEO信息。

【文章标题】
{title}

【文章内容】
{content}

【任务要求】
请仔细阅读文章标题和内容，理解文章的核心主题和关键信息，然后生成以下SEO内容：

1. **摘要（summary）**：
   - 生成一段简洁、准确、吸引人的中文摘要
   - 必须准确概括文章的核心内容和主要观点
   - 字数严格控制在68字以内（包括标点符号）
   - 语言要流畅自然，具有吸引力
   - 不要使用"本文"、"文章"等词开头

2. **关键词（keywords）**：
   - 根据文章标题、内容和摘要，提取3-6个最相关的关键词
   - 关键词要符合Google SEO规范，具有搜索价值
   - 优先选择用户可能搜索的核心词汇
   - 使用英文逗号,隔开，不要有空格
   - 格式示例：关键词1,关键词2,关键词3

3. **Slug（slug）**：
   - 根据文章的标题和核心内容，生成一个适用于URL的英文slug
   - 全部使用小写字母
   - 只包含字母、数字和连字符（-）
   - 长度控制在30-50个字符之间
   - 要简洁、有意义、易于理解
   - 格式示例：article-title-seo-friendly

【输出格式】
请严格按照以下JSON格式返回，不要添加任何其他文字说明：
{{
    "summary": "这里填写68字以内的中文摘要",
    "keywords": "关键词1,关键词2,关键词3",
    "slug": "article-slug-format"
}}

请开始生成：""",
        'doubao': """你是一个专业的SEO内容优化专家。请根据以下文章内容，生成高质量的SEO信息。

【文章标题】
{title}

【文章内容】
{content}

【任务要求】
请仔细阅读文章标题和内容，理解文章的核心主题和关键信息，然后生成以下SEO内容：

1. **摘要（summary）**：
   - 生成一段简洁、准确、吸引人的中文摘要
   - 必须准确概括文章的核心内容和主要观点
   - 字数严格控制在68字以内（包括标点符号）
   - 语言要流畅自然，具有吸引力
   - 不要使用"本文"、"文章"等词开头

2. **关键词（keywords）**：
   - 根据文章标题、内容和摘要，提取3-6个最相关的关键词
   - 关键词要符合Google SEO规范，具有搜索价值
   - 优先选择用户可能搜索的核心词汇
   - 使用英文逗号,隔开，不要有空格
   - 格式示例：关键词1,关键词2,关键词3

3. **Slug（slug）**：
   - 根据文章的标题和核心内容，生成一个适用于URL的英文slug
   - 全部使用小写字母
   - 只包含字母、数字和连字符（-）
   - 长度控制在30-50个字符之间
   - 要简洁、有意义、易于理解
   - 格式示例：article-title-seo-friendly

【输出格式】
请严格按照以下JSON格式返回，不要添加任何其他文字说明：
{{
    "summary": "这里填写68字以内的中文摘要",
    "keywords": "关键词1,关键词2,关键词3",
    "slug": "article-slug-format"
}}

请开始生成："""
    }
    
    PROMPT_CONFIG[model] = default_prompts[model]
    logger.info(f"提示词已重置为默认值 - 模型: {model}")
    
    return {'message': '提示词已重置', 'prompt': PROMPT_CONFIG[model]}


# ==================== 认证相关API ====================

@app.post("/api/auth/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    """用户登录"""
    from fastapi.responses import JSONResponse
    token = authenticate(username, password)
    if token:
        response = JSONResponse(content={"authenticated": True})
        response.set_cookie(
            key="session_token",
            value=token,
            httponly=True,
            max_age=86400,  # 24小时
            samesite="lax"
        )
        return response
    else:
        raise HTTPException(status_code=401, detail="用户名或密码错误")


@app.post("/api/auth/check")
async def check_auth(request: Request):
    """检查认证状态"""
    token = get_session_token(request)
    is_authenticated = verify_session(token)
    return {"authenticated": is_authenticated}


@app.post("/api/auth/logout")
async def logout(request: Request):
    """用户登出"""
    from fastapi.responses import JSONResponse
    token = get_session_token(request)
    delete_session(token)
    response = JSONResponse(content={"authenticated": False})
    response.delete_cookie(key="session_token")
    return response


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

