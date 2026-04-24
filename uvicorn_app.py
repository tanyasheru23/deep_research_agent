import gradio as gr
from dotenv import load_dotenv
from core.research_manager import ResearchManager
from core.cache import clear_cache, cache_stats

load_dotenv(override=True)


async def run(query: str, depth: str, send_email: bool, export_pdf: bool):
    """Stream research progress and final report into the UI."""
    if not query.strip():
        yield "⚠️ Please enter a research query.", "", ""
        return

    manager = ResearchManager()
    log_lines = []
    report_md = ""
    pdf_path_str = ""

    async for chunk in manager.run(
        query,
        depth=depth,
        send_email=send_email,
        export_pdf_flag=export_pdf,
    ):
        # Detect the final report (long markdown)
        if chunk.startswith(">") or chunk.startswith("##"):
            report_md = chunk
        elif chunk.startswith("✅ PDF saved:"):
            pdf_path_str = chunk.replace("✅ PDF saved:", "").strip()
            log_lines.append(chunk)
        else:
            log_lines.append(chunk)

        yield "\n".join(log_lines), report_md, pdf_path_str


def get_cache_info():
    stats = cache_stats()
    return (
        f"**Cache entries:** {stats['total_entries']}  \n"
        f"**Oldest entry:** {stats['oldest_entry_hours_ago']} hours ago  \n"
        f"**DB location:** `{stats['db_path']}`"
    )


def handle_clear_cache():
    n = clear_cache()
    return f"✅ Cleared {n} cached entries."


# ── UI Layout ──────────────────────────────────────────────────────────────
with gr.Blocks(theme=gr.themes.Soft(primary_hue="sky"), title="Deep Research") as ui:
    gr.Markdown("# 🔬 Deep Research Agent")
    gr.Markdown("Enter a query and choose your depth. The agent plans, searches, synthesises, and exports.")

    with gr.Row():
        with gr.Column(scale=3):
            query_textbox = gr.Textbox(
                label="Research query",
                placeholder="e.g. What are the latest breakthroughs in quantum error correction?",
                lines=2,
            )
        with gr.Column(scale=1):
            depth_radio = gr.Radio(
                choices=["quick", "standard", "deep"],
                value="standard",
                label="Depth",
                info="quick=3 searches, standard=5+gap fill, deep=8+gap fill+gpt-4o",
            )

    with gr.Row():
        email_toggle = gr.Checkbox(value=False, label="📧 Send email report")
        pdf_toggle = gr.Checkbox(value=True, label="📄 Export PDF")

    run_button = gr.Button("▶ Run Research", variant="primary", size="lg")

    with gr.Tabs():
        with gr.TabItem("📊 Progress"):
            progress_box = gr.Markdown(label="Status log")

        with gr.TabItem("📝 Report"):
            report_out = gr.Markdown(label="Generated report")

        with gr.TabItem("📄 PDF"):
            pdf_path_out = gr.Textbox(label="PDF saved to", interactive=False)
            gr.Markdown("_Open the path above in your file browser or PDF viewer._")

        with gr.TabItem("🗄️ Cache"):
            cache_info = gr.Markdown(get_cache_info())
            refresh_btn = gr.Button("🔄 Refresh stats")
            clear_btn = gr.Button("🗑️ Clear cache", variant="stop")
            clear_status = gr.Markdown()

    # ── Event bindings ─────────────────────────────────────────────────
    run_button.click(
        fn=run,
        inputs=[query_textbox, depth_radio, email_toggle, pdf_toggle],
        outputs=[progress_box, report_out, pdf_path_out],
    )
    query_textbox.submit(
        fn=run,
        inputs=[query_textbox, depth_radio, email_toggle, pdf_toggle],
        outputs=[progress_box, report_out, pdf_path_out],
    )
    refresh_btn.click(fn=get_cache_info, outputs=cache_info)
    clear_btn.click(fn=handle_clear_cache, outputs=clear_status)


if __name__ == "__main__":
    ui.launch(inbrowser=True)
