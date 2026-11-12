// subagents-tabs: the header of the "subagents" stack: Claude | pi.
import { View, div } from "gpui-kit";
import { h_flex } from "gpui-base";
import { run, theme, layout } from "herdr";

const STACK = "subagents";
const TABS = [["subagents-claude", "Claude"], ["subagents-pi", "pi"]];
function find(node, id) {
  if (node?.id === id) return node;
  for (const c of node?.children ?? []) { const f = find(c, id); if (f) return f; }
  return null;
}

export default class SubagentsTabs extends View {
  render() {
    const t = theme();
    const active = find(layout(), STACK)?.active ?? TABS[0][0];
    return h_flex().id("root").size_full().px(8).gap(4).items_center().bg(t.chrome)
      .border_b(1).border_color(t.border)
      .children(TABS.map(([id, label]) => {
        const on = id === active;
        return div().id(`tab-${id}`).px(10).h(22).rounded(6).flex().items_center().cursor_pointer()
          .text_size(11.5).font_semibold().text_color(on ? t.foreground : t.dim)
          .bg(on ? t.raised : t.chrome).hover((s) => s.bg(t.hover))
          .on_click(() => run("layout.select", { stack: STACK, child: id }))
          .child(label);
      }));
  }
}
