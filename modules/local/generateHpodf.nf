process generateHpodf {
    cpus 1

    // publishDir "published/$context.run_id/hpodf", mode: 'copy'
    tag "$context.run_id"

    input:
    tuple val(context), path(inputhpo, name: 'input.hpos.txt')

    output:
    tuple val(context), path("./${context.run_id}.hpodf.csv")

    script:
    """
    #!${moduleDir}/../../.venv/bin/python

    import pandas as pd
    import json

    def get_wholehpodf(hp_json_path):
        with open(hp_json_path) as file:
            data = json.load(file)
        df = pd.DataFrame([{
            "id": node['id'].split('/')[-1],
            "name": node['lbl'],
            "synonyms": [syn.get('val') for syn in node.get('meta', {}).get('synonyms', [])],
            "definition": node.get('meta', {}).get('definition', {}).get('val', ''),
        } for node in data['graphs'][0]['nodes'] if node.get("type") == "CLASS"])
        df["id"] = df["id"].str.replace("HP_", "HP:")
        return df

    if __name__ == "__main__":
        wholehpodf = get_wholehpodf("${projectDir}/resources/hp.json")
        hpodf = pd.read_csv("${inputhpo}", header=None, names=["id"]).merge(wholehpodf, on="id", how="left")
        hpodf.to_csv("./${context.run_id}.hpodf.csv", index=False)
    """

    stub:
    """
    #!${moduleDir}/../../.venv/bin/python
    import csv
    from pathlib import Path

    ids = [line.strip() for line in Path("input.hpos.txt").read_text().splitlines() if line.strip()]
    if not ids:
        ids = ["HP:STUB"]

    with open("${context.run_id}.hpodf.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["id", "name", "synonyms", "definition"])
        writer.writeheader()
        for hp_id in ids:
            writer.writerow({
                "id": hp_id,
                "name": f"Stub term for {hp_id}",
                "synonyms": "[]",
                "definition": "Stub definition produced with -stub-run"
            })
    """
}
