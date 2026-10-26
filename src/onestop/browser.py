"""Small, internal helpers for the portal's native widget controllers."""

from datetime import datetime, timezone

from .models import ActionResult, OneStopError


SCOPES = """
const scopes = [...document.querySelectorAll('div[widget][data]')]
  .map(e => angular.element(e).scope()).filter(s => s && s.widget && s.data);
const scope = id => {
  const matches = scopes.filter(s => s.widget.id === id || s.widget.name === id);
  if (matches.length !== 1) throw new Error('Expected one native widget');
  return matches[0];
};
const pick = (o, names) => Object.fromEntries(names.filter(n => n in o).map(n => [n,o[n]]));
const catalogForm = () => {
  const item=scope('ntu-widget-sc-cat-item-v2').data.sc_cat_item;
  for(const e of document.querySelectorAll('[form-model][mandatory]')) {
    const s=angular.element(e).isolateScope();
    if(s?.formModel?.sys_id===item?.sys_id && typeof s.getGlideForm==='function') {
      const g=s.getGlideForm();
      if(g && g.getUniqueValue()===item.sys_id) return g;
    }
  }
  throw new Error('Native catalog form is not initialized');
};
"""


def evaluate(page, body, args=None, asynchronous=False):
    prefix = "async " if asynchronous else ""
    return page.evaluate(prefix + "(args) => {" + SCOPES + body + "}", args)


def commit(session, revision, function):
    """Run one write attempt. An uncertain outcome must never be auto-retried."""
    session.before_write(revision)
    try:
        return function()
    except OneStopError:
        raise
    except Exception:
        raise OneStopError(
            "The portal action may have completed, but its result could not be verified. "
            "Check the relevant portal record before repeating this action."
        ) from None
    finally:
        session._cache.clear()


def action_result(operation, source_url, resource_id=None, verified=False,
                  outcome="completed", message=None, references=None):
    return ActionResult(operation=operation, completed_at=datetime.now(timezone.utc), source_url=source_url,
                        resource_id=resource_id, verified=verified, outcome=outcome,
                        message=message, references=references or [])


def picker_query(page, element_code, query, page_number=1, extra_args=None):
    if not isinstance(query, str) or len(query) > 100 or any(ord(c) < 32 or ord(c) == 127 or c == '^' for c in query):
        raise OneStopError("Reference searches accept at most 100 characters without control characters or encoded-query operators.")
    if type(page_number) is not int or not 1 <= page_number <= 100:
        raise OneStopError("Reference picker pages start at 1 and are capped at 100.")
    body = element_code + r"""
      if(!element) throw new Error('Native reference picker missing');
      const select=jQuery(element).data('select2');
      if(!select?.opts?.query) throw new Error('Native reference picker missing');
      const result=await new Promise((resolve,reject)=>{
        const timeout=setTimeout(()=>reject(new Error('Reference query timed out')),20000);
        select.opts.query({term:args.query,page:args.page,callback:r=>{clearTimeout(timeout);resolve(r);}});
      });
      const values=(result.results||[]).map(r=>{
        const value=typeof select.opts.id==='function'?select.opts.id(r):r[select.opts.id||'id'];
        let label=select.opts.formatSelection?select.opts.formatSelection(r):r.text;
        if(typeof label!=='string') label=jQuery(label).text();
        const parsed=new DOMParser().parseFromString(label||'','text/html').body.textContent;
        return {value:String(value??r.sys_id??r.id),label:parsed.trim()};
      });
      return {choices:values,more:result.more===true};
    """
    return evaluate(page, body, {**(extra_args or {}), "query": query, "page": page_number}, asynchronous=True)
