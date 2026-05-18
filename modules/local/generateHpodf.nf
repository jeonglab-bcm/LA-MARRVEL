process generateHpodf {
    cpus 1

    // publishDir "published/$context.run_id/hpodf", mode: 'copy'
    tag "$context.run_id"

    input:
    path inputhpo, name: 'input.hpos.txt'
    val context

    output:
    path "./${context.run_id}.hpodf.csv"

    script:
    """
    #!/usr/bin/env python

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
}
