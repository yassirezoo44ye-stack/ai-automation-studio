// Source inventory, not an end-to-end test or a claim that an action succeeded.
import fs from "node:fs";
import { execFileSync } from "node:child_process";
import ts from "typescript";

const files = execFileSync("rg", ["--files", "src/renderer"], { encoding: "utf8" }).trim().split("\n")
  .filter(path => path.endsWith(".tsx") && !/(__tests__|\.test\.)/.test(path)).sort();
const actions = [];
for (const path of files) {
  const source = fs.readFileSync(path, "utf8");
  const tree = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  function visit(node) {
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const element = node.tagName.getText(tree);
      const attributes = node.attributes.properties.filter(ts.isJsxAttribute);
      const attr = name => attributes.find(a => a.name.getText(tree) === name);
      const handler = attr("onClick") ?? attr("onSubmit") ?? attr("onPointerDown") ?? attr("onMouseDown");
      const isButton = element === "button" || element === "GoldButton";
      if (isButton || handler || (element === "a" && attr("href"))) {
        let form = null;
        for (let parent = node.parent; parent; parent = parent.parent) {
          if (ts.isJsxElement(parent) && parent.openingElement.tagName.getText(tree) === "form") {
            form = parent.openingElement; break;
          }
        }
        const type = attr("type")?.initializer?.getText(tree).replaceAll('"', "");
        const implicitSubmit = element === "button" && !type && form;
        const submit = type === "submit" || implicitSubmit;
        const formAction = form?.attributes.properties.filter(ts.isJsxAttribute).some(a => ["onSubmit", "action"].includes(a.name.getText(tree)));
        actions.push({
          path, line: tree.getLineAndCharacterOfPosition(node.getStart()).line + 1, element,
          handler: handler?.initializer?.getText(tree).replace(/\s+/g, " ").slice(0, 500) ?? null,
          destination: attr("href")?.initializer?.getText(tree) ?? null,
          hasDisabledGuard: Boolean(attr("disabled")),
          wiring: handler ? "handler" : attr("href") ? "link" : submit && formAction ? "form-submit" : attr("disabled") ? "disabled-or-conditional" : "manual-review",
          verification: "source-only",
        });
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(tree);
}
const report = {
  note: "JSX source sites, not runtime button counts. Handlers and guards do not prove successful execution. Functional evidence is recorded separately in docs/platform-actions-review.md.",
  filesScanned: files.length,
  nativeButtons: actions.filter(a => a.element === "button").length,
  composedButtons: actions.filter(a => a.element === "GoldButton").length,
  actionSites: actions.length,
  manualReview: actions.filter(a => a.wiring === "manual-review").length,
  actions,
};
const output = process.argv[2];
if (output) fs.writeFileSync(output, JSON.stringify(report, null, 2) + "\n");
else process.stdout.write(JSON.stringify(report, null, 2) + "\n");
