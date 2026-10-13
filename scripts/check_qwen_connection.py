import os

from dotenv import load_dotenv
from openai import OpenAI

# 从本地 .env 读取配置，但不会打印密钥
load_dotenv()

client = OpenAI(
    api_key=os.environ["DASHSCOPE_API_KEY"],
    base_url=os.environ["DASHSCOPE_BASE_URL"],
)

response = client.chat.completions.create(
    model=os.environ["DASHSCOPE_MODEL"],
    messages=[
        {
            "role": "user",
            "content": "请只回复：连接成功",
        }
    ],
    temperature=0,
    max_tokens=20,
    extra_body={"enable_thinking": False},
)

print("模型回复：", response.choices[0].message.content)
print("输入 Token：", response.usage.prompt_tokens)
print("输出 Token：", response.usage.completion_tokens)
