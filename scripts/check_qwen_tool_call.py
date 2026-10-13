"""Verify that Qwen selects the expected order-query tool and arguments."""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from customer_support.store import get_order_status  # noqa: E402

load_dotenv()

client = OpenAI(
    api_key=os.environ["DASHSCOPE_API_KEY"],
    base_url=os.environ["DASHSCOPE_BASE_URL"],
)

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": "查询电商订单状态，需要订单号和手机号后四位。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "订单号，例如 ORD1001",
                    },
                    "phone_last4": {
                        "type": "string",
                        "description": "下单手机号后四位",
                    },
                },
                "required": ["order_id", "phone_last4"],
                "additionalProperties": False,
            },
        },
    }
]

messages = [
    {
        "role": "user",
        "content": "帮我查询订单 ORD1001，手机号后四位 8821。",
    }
]

response = client.chat.completions.create(
    model=os.environ["DASHSCOPE_MODEL"],
    messages=messages,
    tools=tools,
    tool_choice="auto",
    temperature=0,
    max_tokens=200,
    extra_body={"enable_thinking": False},
)

message = response.choices[0].message

if message.tool_calls:
    tool_call = message.tool_calls[0]
    print("模型选择的工具：", tool_call.function.name)
    print("模型生成的参数：", tool_call.function.arguments)

    if tool_call.function.name != "get_order_status":
        raise ValueError(f"不允许执行未知工具：{tool_call.function.name}")

    arguments = json.loads(tool_call.function.arguments)
    tool_result = get_order_status(
        order_id=arguments["order_id"],
        phone_last4=arguments["phone_last4"],
    )
    print("数据库实际返回：", json.dumps(tool_result, ensure_ascii=False))

    messages.append(message)
    messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps(tool_result, ensure_ascii=False),
        }
    )

    final_response = client.chat.completions.create(
        model=os.environ["DASHSCOPE_MODEL"],
        messages=messages,
        tools=tools,
        temperature=0,
        max_tokens=100,
        extra_body={"enable_thinking": False},
    )
    print("模型最终回答：", final_response.choices[0].message.content)
    print(
        "第二次调用 Token：",
        final_response.usage.prompt_tokens,
        "输入 /",
        final_response.usage.completion_tokens,
        "输出",
    )
else:
    print("模型没有选择工具，回复：", message.content)
