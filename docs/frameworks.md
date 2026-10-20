# Framework adapters

Backstop sits underneath the application, at the transport. A framework calls
the SDK, the SDK goes through the transport, and the transport enforces. That
works with any framework, because the framework does not know Backstop is
there.

The adapters here do something else: they give a framework's own callback
surface a way to reach Backstop's tenant scoping, so a framework run can be
labelled without every call site being edited by hand.

The framework imports are **deferred**: importing `backstop.adapters` never
requires LangChain, LlamaIndex, CrewAI or AutoGen to be installed. The
adapters import the framework only when you ask for that framework's bridge,
and a missing framework is a clear error naming the package to install.

---

## Why tenant scoping is worth it

The spend ledger records what each request cost, and the ledger's usefulness
is almost entirely in the *attribution*: which team, which feature, which
session. Without it, every row is `(unattributed)` and the charge-back cannot
be split.

Attribution is normally declared by hand, at the call site:

```python
from backstop import attribution

with attribution(team="payments", feature="checkout-v2"):
    client.chat.completions.create(...)
```

That is correct and explicit, and it is the right answer for a codebase you
control. It is also a line to add to every call site, and a line to forget.

An adapter gives a framework's callbacks a tenant id, so the calls a framework
makes on your behalf are labelled without editing them.

---

## The adapters

### LangChain

```python
from backstop import BackstopConfig
from backstop.adapters import get_langchain_handler

config = BackstopConfig()
handler = get_langchain_handler(config, tenant_id="payments")
chain = MyChain(callbacks=[handler])
```

The handler is a LangChain `BaseCallbackHandler`. It reports the model and the
token counts to Backstop's adapter, and carries the tenant id you gave it.

### LlamaIndex

```python
from backstop import BackstopConfig
from backstop.adapters import get_llama_index_callback

config = BackstopConfig()
callback = get_llama_index_callback(config, tenant_id="payments")
index = VectorStoreIndex.from_documents(docs, callbacks=[callback])
```

### The framework-agnostic one

```python
from backstop.adapters import BackstopAdapter

adapter = BackstopAdapter(config, tenant_id="payments")
adapter.on_llm_start("gpt-4o", estimated_tokens=120)
adapter.on_llm_end("gpt-4o", prompt_tokens=120, completion_tokens=30)
```

`BackstopAdapter` has no framework dependency at all. Call `on_llm_start` and
`on_llm_end` from whatever callback surface your framework has, and the
enforcement at the transport is unchanged.

---

## What an adapter does and does not do

**Does:**

- carry a tenant id into a framework's callback surface;
- report the model and the token counts back to Backstop's adapter;
- keep the framework's import optional;
- leave the transport's enforcement exactly where it was.

**Does not:**

- **wrap the SDK client for you.** Backstop still wraps the client with
  `Backstop.wrap()`. An adapter is about labelling, not enforcement.
- **change any enforcement behaviour.** A budget configured on the transport
  behaves identically whether or not an adapter is installed.
- **read the framework's prompts.** It reads the run's identity, not its
  content.
- **infer a team from a run name.** If your organisation has a definition of
  "team", an adapter that guesses one is worse than an explicit
  `team="payments"`.

---

## The explicit path, still

Nothing about the adapters changes the recommended way to attribute spend.
Where you can say which team a request belongs to, say it:

```python
from backstop import attribution

with attribution(team="payments", feature="checkout-v2"):
    client.chat.completions.create(...)
```

An explicit scope is always better than an inferred one. The adapters are
there for the calls you did not write, and for the frameworks that already
know who is calling.

---

## What it does not do

- **It is not framework-native enforcement.** There is no "Backstop callback
  that blocks the chain". Enforcement is at the transport, where it can see
  every attempt including the ones a framework retries.
- **It does not cover every framework.** The adapters here cover the ones
  with a usable callback surface. For anything else, declare the attribution
  at the call site — it is one line and it is explicit.
- **It is not a substitute for attribution you own.** See above.
