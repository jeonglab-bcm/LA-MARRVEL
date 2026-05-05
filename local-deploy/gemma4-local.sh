nextflow run ./workflows/rerank \
  --genecsv "/home/zache/Data/LA-MARRVEL/*.gene.csv" \
  --hpostxt "/home/zache/Data/LA-MARRVEL/*.hpos.txt" \
  --consideringgenes_g 100 \
  --invocationnumber_n 10 \
  --run_id fullsize_run \
  --model gemma4:e4b \
  --model_url http://localhost:11435/v1