from huggingface_hub import list_datasets

keywords = ["amazon review", "ecommerce review", "product reviews"]
seen = set()

for kw in keywords:
    print(f"\n=== search: {kw} ===")
    for ds in list_datasets(search=kw, limit=20):
        if ds.id in seen:
            continue
        seen.add(ds.id)
        print(ds.id)
