

def place_limit_order(
        self, symbol: str, side: str, position_side: str, quantity: float, price: float
    ) -> AdapterResponse[OrderPlacementResult]:
        """
        下限价单

        Args:
            symbol: 交易对
            side: 方向("BUY"或"SELL")
            position_side: 持仓方向("LONG"或"SHORT")
            quantity: 数量
            price: 价格

        Returns:
            AdapterResponse: 包含订单信息的响应
        """
        # self.judge_auth_token_expired()
        try:
            for i in range(2):
                self.judge_auth_token_expired()
                if side == "BUY":
                    order_side = OrderSide.Buy
                else:
                    order_side = OrderSide.Sell
                
                size = Decimal(str(quantity))
                price = Decimal(str(price))
                client_id = self.get_client_order_id()

                # Build the order
                order = self.build_limit_order_sync(symbol, order_side, size, price, client_id)
                # Sign the order
                signature = self.sign_order_sync(self.paradex_config, self.paradex_account_address, self.paradex_account_private_key, order)
                order.signature = signature

                # Convert order to dict
                order_dict = order.dump_to_dict()
                
                # Prepare headers
                headers = {
                    "Authorization": f"Bearer {self.jwt_token}",
                    "Content-Type": "application/json"
                }
                url = self.base_url + "/orders"

                response = requests.post(url, headers=headers, json=order_dict, proxies=self.proxies,  timeout=60)
                status_code = response.status_code
                response_json = response.json()
                response_json["status_code"] = status_code
                
                if status_code == 201:
                    logger.info(f"Order Created: {status_code} | Response: {response_json}")

                    order_placement_result = OrderPlacementResult(
                        symbol=symbol,
                        order_id=response_json["id"],
                        order_qty=quantity,
                        order_price=price,
                        side=side,
                        position_side=position_side,
                        api_resp=response_json,
                    )

                    result =  AdapterResponse(
                        success=True, data=order_placement_result, error_msg=""
                    )
                    return result
                else:
                    logger.warning(f"Unable to [POST] /orders Status Code:{status_code}")
                    logger.warning(f"Response: {response_json}")
                    self.check_error(response_json)
                    result = AdapterResponse(
                        success=False,
                        data=None,
                        error_msg=f"Response: {response_json}",
                    )
                    if i == 1:
                        return result
                    else:
                        continue
            
        except Exception as e:
            logger.error(f"下限价单失败: {e}")
            return AdapterResponse(
                success=False,
                data=None,
                error_msg=str(e),
            )