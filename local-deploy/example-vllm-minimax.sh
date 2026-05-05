#!/bin/bash
# PROFILE: MiniMax-M2-AWQ Example
# DESCRIPTION: vLLM serving MiniMax-M2-AWQ with Ray distributed backend

~/Docker/spark-vllm-docker/launch-cluster.sh --solo exec\
  vllm serve google/gemma-4-E4B \
    --port 8765 \
    --host localhost \
    --gpu-memory-utilization 0.2 \
    -tp 2 \
    --distributed-executor-backend ray \
    --load-format fastsafetensors \
    --enable-auto-tool-choice \
    --tool-call-parser minimax_m2 \
    --reasoning-parser minimax_m2_append_think
