#!/bin/bash
# PROFILE: MiniMax-M2-AWQ Example
# DESCRIPTION: vLLM serving MiniMax-M2-AWQ with Ray distributed backend

MODEL="${1:-${DEFAULT_LOCAL_MODEL:?No model specified and DEFAULT_LOCAL_MODEL is not set}}"

~/Docker/spark-vllm-docker/launch-cluster.sh --solo exec\
  vllm serve "$MODEL" \
    --port 8765 \
    --host localhost \
    --max-model-len 32768 \
    --gpu-memory-utilization 0.8 \
    --enable-auto-tool-choice \
    --tool-call-parser gemma4 \
    #--reasoning-parser gemma4 \
    #--chat-template examples/tool_chat_template_gemma4.jinja