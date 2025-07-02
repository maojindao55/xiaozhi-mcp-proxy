#!/usr/bin/env python3
"""
标准输入输出的 MCP 客户端
模仿传统 MCP 客户端的行为，用于与 mcp_pipe.py 配合使用
"""

import asyncio
import aiohttp
import json
import sys
import logging
import os

# 配置日志到 stderr，避免干扰 stdin/stdout 通信
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

class StdioMcpClient:
    def __init__(self, mcp_url=None):
        # 优先从环境变量读取 MCP_URL，否则使用默认值或传入参数
        self.mcp_url = mcp_url or os.getenv("MCP_URL", "http://127.0.0.1:12306/mcp")
        self.session = None
        self.session_id = None
        self.initialized = False
        
    async def start(self):
        """启动客户端"""
        self.session = aiohttp.ClientSession()
        logger.info(f"MCP 客户端启动，连接到: {self.mcp_url}")
        
        # 开始处理输入输出
        await asyncio.gather(
            self.handle_stdin(),
            self.keep_alive()
        )
        
    async def handle_stdin(self):
        """处理标准输入的消息"""
        while True:
            try:
                # 从 stdin 读取一行
                line = await asyncio.get_event_loop().run_in_executor(
                    None, sys.stdin.readline
                )
                
                if not line:
                    logger.info("输入流结束")
                    break
                    
                line = line.strip()
                if not line:
                    continue
                    
                logger.info(f"收到输入: {line[:100]}...")
                
                try:
                    # 解析 JSON 消息
                    message = json.loads(line)
                    
                    # 发送到 MCP 服务器
                    response = await self.send_to_mcp(message)
                    
                    # 输出响应到 stdout
                    if response:
                        output = json.dumps(response) if isinstance(response, dict) else str(response)
                        print(output, flush=True)
                        logger.info(f"输出响应: {output[:100]}...")
                        
                        # 如果是初始化响应，自动发送 tools/list
                        if (not self.initialized and 
                            message.get('method') == 'initialize'):
                            await self.auto_send_tools_list()
                            
                except json.JSONDecodeError:
                    logger.error(f"无效的 JSON: {line}")
                except Exception as e:
                    logger.error(f"处理消息错误: {e}")
                    
            except Exception as e:
                logger.error(f"读取输入错误: {e}")
                break
                
    async def send_to_mcp(self, message):
        """发送消息到 MCP 服务器"""
        if not self.session:
            return None
            
        try:
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json, text/event-stream'
            }
            
            # 如果有会话ID，添加到请求头
            if self.session_id:
                headers['mcp-session-id'] = self.session_id
            
            async with self.session.post(self.mcp_url, json=message, headers=headers) as response:
                # 检查是否是初始化请求，需要提取会话ID
                if message.get('method') == 'initialize' and response.status == 200:
                    session_id = response.headers.get('mcp-session-id')
                    if session_id:
                        self.session_id = session_id
                        logger.info(f"获得 MCP 会话ID: {self.session_id}")
                
                if response.status in [200, 202]:
                    content_type = response.headers.get('content-type', '')
                    if 'application/json' in content_type:
                        return await response.json()
                    else:
                        text_response = await response.text()
                        # 解析 SSE 格式
                        if text_response.startswith('event: message'):
                            lines = text_response.strip().split('\n')
                            for line in lines:
                                if line.startswith('data: '):
                                    return json.loads(line[6:])
                        return text_response
                else:
                    error_text = await response.text()
                    logger.error(f"MCP 请求失败: {response.status}, 错误: {error_text}")
                    return {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": response.status,
                            "message": f"MCP server error: {error_text}"
                        },
                        "id": message.get("id")
                    }
                    
        except Exception as e:
            logger.error(f"发送 MCP 消息错误: {e}")
            return {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32603,
                    "message": f"Internal error: {str(e)}"
                },
                "id": message.get("id")
            }
    
    async def auto_send_tools_list(self):
        """在初始化后自动发送 tools/list 请求"""
        logger.info("发送自动 tools/list 请求")
        
        # 等待一小段时间确保服务器准备好
        await asyncio.sleep(0.5)
        
        tools_request = {
            "jsonrpc": "2.0",
            "id": 9999,
            "method": "tools/list"
        }
        
        response = await self.send_to_mcp(tools_request)
        if response:
            output = json.dumps(response) if isinstance(response, dict) else str(response)
            print(output, flush=True)
            logger.info(f"自动输出 tools/list 响应: {output[:100]}...")
            
            # 记录工具数量
            try:
                if isinstance(response, dict) and 'result' in response and 'tools' in response['result']:
                    tools_count = len(response['result']['tools'])
                    logger.info(f"✅ 自动获取了 {tools_count} 个 MCP 工具")
                    self.initialized = True
            except Exception as e:
                logger.debug(f"解析工具列表时出错: {e}")
    
    async def keep_alive(self):
        """保持程序运行"""
        while True:
            await asyncio.sleep(30)
            logger.debug("MCP 客户端运行中...")
    
    async def cleanup(self):
        """清理资源"""
        if self.session:
            await self.session.close()

async def main():
    """主函数"""
    client = StdioMcpClient()
    try:
        await client.start()
    except KeyboardInterrupt:
        logger.info("程序被中断")
    finally:
        await client.cleanup()

if __name__ == "__main__":
    asyncio.run(main()) 