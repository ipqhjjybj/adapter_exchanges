import time
import requests
from typing import Dict, Tuple
from starknet_py.common import int_from_bytes
from starknet_py.net.signer.stark_curve_signer import KeyPair
import sys
import os

sys.path.append("/Users/shenzhuoheng/quant_yz/git/adapter_exchanges")
sys.path.append("/home/ec2-user/test_lighter_dex/adapter_exchanges")

from paradex_utils import build_auth_message, get_account
from src.log_kit import logger


class ParadexSubKeyTokenGenerator:
    """
    Paradex子密钥Token生成器
    该类专门处理使用sub_key来生成JWT token的功能
    """
    
    def __init__(self, master_account_address: str, sub_private_key: str, proxy_url: str = None):
        """
        初始化子密钥Token生成器
        
        Args:
            master_account_address: 主账户地址
            sub_private_key: 子密钥私钥
            proxy_url: 代理URL（可选）
        """
        self.base_url = "https://api.prod.paradex.trade/v1"
        self.master_account_address = master_account_address
        self.sub_private_key = sub_private_key
        
        if proxy_url:
            self.proxies = {
                "http": proxy_url,
                "https": proxy_url
            }
        else:
            self.proxies = None
        
        # Token缓存
        self.jwt_token = None
        self.token_expiry = 0
        
        # 获取系统配置
        self.paradex_config = self._get_paradex_config()
        assert self.paradex_config is not None, "获取Paradex配置失败"
        assert len(self.paradex_config) > 0, "Paradex配置为空"
    
    def _get_paradex_config(self) -> Dict:
        """
        获取Paradex系统配置
        """
        logger.info("获取Paradex系统配置...")
        path = "/system/config"
        headers = {"accept": "application/json"}
        
        try:
            response = requests.get(
                self.base_url + path, 
                headers=headers, 
                proxies=self.proxies, 
                timeout=60
            )
            response_json = response.json()
            
            if response.status_code == 200:
                logger.info("成功获取Paradex配置")
                return response_json
            else:
                logger.error(f"获取配置失败，状态码: {response.status_code}")
                logger.error(f"响应内容: {response_json}")
                return {}
                
        except Exception as e:
            logger.error(f"获取Paradex配置时发生异常: {e}")
            return {}
    
    def _create_sub_key_account(self) -> object:
        """
        使用子密钥创建账户实例
        """
        try:
            # 使用主账户地址和子密钥创建账户
            account = get_account(
                self.master_account_address, 
                self.sub_private_key, 
                self.paradex_config
            )
            return account
        except Exception as e:
            logger.error(f"创建子密钥账户失败: {e}")
            raise
    
    def generate_jwt_token_with_subkey(self, token_usage: str = "interactive") -> Tuple[str, int]:
        """
        使用子密钥生成JWT token
        
        Args:
            token_usage: token使用类型，默认为'interactive'
            
        Returns:
            Tuple[str, int]: (jwt_token, expiry_timestamp)
        """
        try:
            # 获取链ID
            chain_id = int_from_bytes(self.paradex_config["starknet_chain_id"].encode())
            
            # 创建子密钥账户
            sub_account = self._create_sub_key_account()
            
            # 生成时间戳
            now = int(time.time())
            expiry = now + 24 * 60 * 60 * 7  # 7天有效期
            
            # 构建认证消息
            message = build_auth_message(chain_id, now, expiry)
            
            # 使用子密钥签名
            signature = sub_account.sign_message(message)
            
            # 准备请求头
            headers = {
                "PARADEX-STARKNET-ACCOUNT": self.master_account_address,
                "PARADEX-STARKNET-SIGNATURE": f'["{signature[0]}","{signature[1]}"]',
                "PARADEX-TIMESTAMP": str(now),
                "PARADEX-SIGNATURE-EXPIRATION": str(expiry),
                "accept": "application/json"
            }
            
            # 构建请求URL
            url = f"{self.base_url}/auth?token_usage={token_usage}"
            
            logger.info(f"使用子密钥请求JWT token: {url}")
            logger.info(f"请求头: {headers}")
            
            # 发送请求
            response = requests.post(url, headers=headers, proxies=self.proxies, timeout=60)
            status_code = response.status_code
            response_json = response.json()
            
            if status_code == 200:
                jwt_token = response_json["jwt_token"]
                logger.info("使用子密钥成功生成JWT token")
                logger.info(f"Token过期时间: {expiry}")
                
                # 更新缓存
                self.jwt_token = jwt_token
                self.token_expiry = expiry
                
                return jwt_token, expiry
            else:
                error_msg = f"使用子密钥生成JWT token失败，状态码: {status_code}, 响应: {response_json}"
                logger.error(error_msg)
                raise Exception(error_msg)
                
        except Exception as e:
            logger.error(f"使用子密钥生成JWT token时发生异常: {e}")
            raise
    
    def get_valid_token(self, force_refresh: bool = False) -> str:
        """
        获取有效的JWT token，如果token即将过期则自动刷新
        
        Args:
            force_refresh: 是否强制刷新token
            
        Returns:
            str: 有效的JWT token
        """
        current_time = int(time.time())
        
        # 检查是否需要刷新token（提前1小时刷新）
        if (force_refresh or 
            self.jwt_token is None or 
            current_time >= self.token_expiry - 3600):
            
            logger.info("Token即将过期或需要刷新，重新生成...")
            jwt_token, expiry = self.generate_jwt_token_with_subkey()
            return jwt_token
        else:
            logger.info("使用缓存的有效token")
            return self.jwt_token
    
    def get_authorized_headers(self) -> Dict[str, str]:
        """
        获取包含Authorization头的请求头
        
        Returns:
            Dict[str, str]: 包含Authorization的请求头
        """
        token = self.get_valid_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "accept": "application/json"
        }
    
    def verify_sub_key_access(self) -> bool:
        """
        验证子密钥是否有访问权限
        
        Returns:
            bool: 验证结果
        """
        try:
            headers = self.get_authorized_headers()
            url = f"{self.base_url}/account"
            
            response = requests.get(url, headers=headers, proxies=self.proxies, timeout=30)
            
            if response.status_code == 200:
                logger.info("子密钥访问验证成功")
                return True
            else:
                logger.error(f"子密钥访问验证失败，状态码: {response.status_code}")
                logger.error(f"响应内容: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"验证子密钥访问权限时发生异常: {e}")
            return False


def create_subkey_token_generator(master_account_address: str, sub_private_key: str, proxy_url: str = None) -> ParadexSubKeyTokenGenerator:
    """
    创建子密钥Token生成器的便捷函数
    
    Args:
        master_account_address: 主账户地址
        sub_private_key: 子密钥私钥
        proxy_url: 代理URL（可选）
        
    Returns:
        ParadexSubKeyTokenGenerator: 子密钥Token生成器实例
    """
    return ParadexSubKeyTokenGenerator(master_account_address, sub_private_key, proxy_url)


if __name__ == "__main__":
    # 示例用法
    master_account_address = "0x58419d41b2986d4f6267ccbb7a53a73bcdd95868771648064eea1d205d56408"
    sub_private_key = "0x0103eca5556d58c37805dcf9ba897f5d5c73e745ca5c4b98bd74a7a9e8443a2a"
    
    # 创建子密钥Token生成器
    token_generator = ParadexSubKeyTokenGenerator(master_account_address, sub_private_key)
    
    try:
        # 生成JWT token
        jwt_token, expiry = token_generator.generate_jwt_token_with_subkey()
        print(f"成功生成JWT Token: {jwt_token}")
        print(f"过期时间戳: {expiry}")
        
        # 验证访问权限
        if token_generator.verify_sub_key_access():
            print("子密钥访问权限验证成功")
        else:
            print("子密钥访问权限验证失败")
            
        # 获取授权头
        auth_headers = token_generator.get_authorized_headers()
        print(f"授权请求头: {auth_headers}")
        
    except Exception as e:
        print(f"执行过程中发生错误: {e}")