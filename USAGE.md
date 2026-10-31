# Usage manual

Message your WhatsApp bot number like any chat. Plain text goes to your **default** model. Commands start with `/`.

## Talking to the bot

| You send | What happens |
| --- | --- |
| `how do I boil an egg?` | Answered by your default model |
| `/gpt <message>` | One message to GPT, regardless of your default |
| `/claude <message>` | One message to Claude, regardless of your default |
| `/reset` | Clears the chat history of your default model |
| `/help` | Lists the commands |

Every reply starts with a tag showing what answered, for example `[gpt-6-astra · low]` or `[claude-sonnet-5-5 · medium]`.

## Choosing a model and effort

```
/use                     show your current default
/use <gpt|claude> [model] [effort]
```

`model` and `effort` are optional and can be in any order. Anything you leave out stays as it was.

**Examples**

| You send | Result |
| --- | --- |
| `/use claude sonnet medium` | Claude Sonnet 5.5 on medium effort |
| `/use gpt best low` | Best GPT model on low effort |
| `/use gpt small` | Smallest GPT model (the starting default) |
| `/use claude high` | Keep the Claude model, change effort to high |
| `/use claude default` | Clear Claude's effort (API default) |
| `/use gpt gpt-5.4-mini` | Any model ID works too |

**Model shortcuts**

| Provider | Shortcut | Model ID |
| --- | --- | --- |
| gpt | `small`, `nano` | `gpt-5.4-nano` (starting default) |
| gpt | `mini` | `gpt-5.4-mini` |
| gpt | `best`, `astra` | `gpt-6-astra` |
| claude | `sonnet` | `claude-sonnet-5-5` (starting default) |
| claude | `opus` | `claude-opus-5-5` |
| claude | `haiku` | `claude-haiku-5-5` |
| claude | `fable` | `claude-fable-5-1` |

**Effort levels:** `low`, `medium`, `high`, `xhigh`, `max`; GPT also accepts `none`; `default` clears it. Lower effort is faster and cheaper, higher thinks harder. Which levels a specific model accepts is decided by the API; if it rejects your choice, the bot replies with the API's error so you can pick another.

## Good to know

- **Settings are remembered per provider and per phone number.** `/use claude sonnet medium`, then `/use gpt best low`, then `/use claude` brings back Claude on medium.
- **History is kept separately for GPT and Claude** (last 16 messages by default). `/reset` clears only your current default model's history.
- **Text messages only.** Images, voice notes and other media are ignored.
- **If a request fails**, you get a short error reply and the failed message isn't added to the history, so you can just resend it.
- **Access control:** set `ALLOWED_PHONE_NUMBERS` on the server to limit who can use the bot. Without it, anyone who messages the number can.
- **Costs:** every message is a paid API call to OpenAI or Anthropic. The smallest GPT model and low effort are the cheapest settings.
