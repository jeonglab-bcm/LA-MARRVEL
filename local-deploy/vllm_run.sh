docker run -it --rm --name gemma4 \
    --ipc=host \
    --network host \
    --shm-size 16G \
    --gpus all \
    -v ~/.cache/huggingface:/root/.cache/huggingface \
    vllm/vllm-openai:gemma4 \
        --model google/gemma-4-26B-A4B-it \
        --max-model-len 32768 \
        --gpu-memory-utilization 0.6 \
        --host 0.0.0.0 \
        --port 8000