

class LightAdapter(object):
    """
    lighter交易所适配器实现
    """
    
    def __init__(self, l1_address: str, apikey_private_key: str, api_key_index: int):
        self.base_url = "https://mainnet.zklighter.elliot.ai"



if __name__ == "__main__":
    import sys
    import os 
    
    lighter_adapter = LightAdapter(
        l1_address="0xA2C9f815302d32757688eB0D6466466105682F54",
        apikey_private_key="9d0a9b5f993c919fd8c2b63598be0753f05dc00ae6fbc2081a180a991bfd360822bcf95322e6e50a",
        api_key_index=2
    )
