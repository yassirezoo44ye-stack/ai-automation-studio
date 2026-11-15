import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { JSDOM } from 'jsdom';
import { describe, expect, it } from 'vitest';

const html = readFileSync(resolve(process.cwd(), 'docs/demos/flow-food-sales-demo.html'), 'utf8');

function launch() {
  const dom = new JSDOM(html, {
    runScripts: 'dangerously',
    url: 'https://example.invalid/demo',
    beforeParse(window) {
      // jsdom does not provide structuredClone in all supported versions.
      window.structuredClone = structuredClone;
    },
  });
  const doc = dom.window.document;
  const click = (id) => {
    const el = doc.getElementById(id);
    expect(el).not.toBeNull();
    el.click();
  };
  const count = (id) => Number(doc.getElementById(id)?.textContent);
  return { dom, doc, click, count };
}

describe('Flow Food Sales synthetic demo', () => {
  it('starts with one open, one blocked and one completed order', () => {
    const { dom, count } = launch();
    expect(count('openCount')).toBe(2);
    expect(count('lateCount')).toBe(1);
    expect(count('doneCount')).toBe(1);
    dom.window.close();
  });

  it('reassigns the selected order and records the action', () => {
    const { dom, doc, click } = launch();
    const owner = doc.getElementById('owner');
    owner.value = 'مشرف المبيعات';
    click('assignBtn');
    expect(doc.getElementById('detail')?.textContent).toContain('مشرف المبيعات');
    expect(doc.getElementById('events')?.textContent).toContain('تغيير المسؤول إلى: مشرف المبيعات');
    dom.window.close();
  });

  it('records a block reason, completion and reopening with updated counters', () => {
    const { dom, doc, click, count } = launch();
    const reason = doc.getElementById('reason');
    reason.value = 'delivery';
    click('blockBtn');
    expect(doc.getElementById('events')?.textContent).toContain('تأخر التوصيل');
    expect(count('lateCount')).toBe(1);
    click('completeBtn');
    expect(count('lateCount')).toBe(0);
    expect(count('doneCount')).toBe(2);
    click('resetBtn');
    expect(count('doneCount')).toBe(1);
    expect(count('openCount')).toBe(2);
    expect(doc.getElementById('events')?.textContent).toContain('أُعيد فتح الطلب');
    dom.window.close();
  });

  it('selects a different order from the table', () => {
    const { dom, doc } = launch();
    const button = Array.from(doc.querySelectorAll('#orders button')).find(
      (el) => el.getAttribute('aria-label') === 'عرض ORD-101',
    );
    expect(button).toBeDefined();
    button.click();
    expect(doc.getElementById('selectedId')?.textContent).toBe('ORD-101');
    dom.window.close();
  });
});
