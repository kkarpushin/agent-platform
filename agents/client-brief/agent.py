"""Справка: программа читает доступные сведения, модель не требуется."""
from sdk import agent


@agent("client-brief")
def app(data, ctx):
    clients = ctx.search("clients", data["client"])
    clients = [r for r in clients if r["data"].get("name", "").casefold() == data["client"].strip().casefold()]
    if not clients:
        raise ValueError("Клиент не найден в доступных знаниях. Проверьте имя в разделе «Знания».")
    client = clients[0]
    cases = ctx.search("cases", client["data"]["industry"])
    sources = [client["id"]] + [r["id"] for r in cases]
    markdown = f"# Справка: {client['data']['name']}\n\n{client['content']}\n\n## Подходящие кейсы\n"
    markdown += "\n".join(f"- {r['title']} [{r['id']}]" for r in cases) or "Подходящих кейсов пока нет."
    markdown += f"\n\nИсточник клиента: [{client['id']}]. Все компании и показатели в примере вымышлены."
    return {"markdown": markdown, "client": client["data"]["name"], "sources": sources}, [
        {"title": "Клиент найден", "detail": f"Источник {client['id']}; прочитана его текущая версия."},
        {"title": "Кейсы подобраны", "detail": f"Найдено: {len(cases)}. Вызов модели не потребовался."}]
