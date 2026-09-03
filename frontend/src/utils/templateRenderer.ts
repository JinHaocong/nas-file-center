/**
 * Client-side template renderer matching the backend implementation in app/organizers/templates.py.
 * Supports:
 * - Brace depth tracking for top-level and nested tokens
 * - {var} simple substitution
 * - {?var: inner_template} conditional substitution with nested inner tokens
 * - Numeric truthy (> 0) and string truthy (!= '' and != '0')
 */

export interface TokenSpan {
  start: number;
  end: number;
  content: string;
}

export function findTopLevelTokens(template: string): TokenSpan[] {
  const tokens: TokenSpan[] = [];
  let i = 0;
  const n = template.length;

  while (i < n) {
    if (template[i] === '{') {
      const start = i;
      let depth = 1;
      i += 1;
      while (i < n && depth > 0) {
        if (template[i] === '{') {
          depth += 1;
        } else if (template[i] === '}') {
          depth -= 1;
        }
        i += 1;
      }
      if (depth === 0) {
        const content = template.slice(start + 1, i - 1);
        tokens.push({ start, end: i, content });
      } else {
        // Unmatched opening brace
        break;
      }
    } else {
      i += 1;
    }
  }

  return tokens;
}

export function renderTemplate(template: string, context: Record<string, any>): string {
  const tokens = findTopLevelTokens(template);
  if (!tokens || tokens.length === 0) {
    return template;
  }

  const result: string[] = [];
  let lastIdx = 0;

  for (const token of tokens) {
    result.push(template.slice(lastIdx, token.start));
    lastIdx = token.end;

    const content = token.content;
    if (content.startsWith('?')) {
      const colonIdx = content.indexOf(':');
      let varName: string;
      let inner: string;
      if (colonIdx !== -1) {
        varName = content.slice(1, colonIdx).trim();
        inner = content.slice(colonIdx + 1);
      } else {
        varName = content.slice(1).trim();
        inner = '';
      }

      const val = context[varName];
      let isActive = false;
      if (typeof val === 'number') {
        isActive = val > 0;
      } else if (typeof val === 'string') {
        isActive = Boolean(val.trim()) && val.trim() !== '0';
      } else if (val !== null && val !== undefined) {
        isActive = Boolean(val);
      }

      if (isActive) {
        result.push(renderTemplate(inner, context));
      }
    } else {
      const colonIdx = content.indexOf(':');
      const varName = colonIdx !== -1 ? content.slice(0, colonIdx).trim() : content.trim();
      const val = context[varName] !== undefined && context[varName] !== null ? context[varName] : '';
      result.push(String(val));
    }
  }

  result.push(template.slice(lastIdx));
  return result.join('');
}
