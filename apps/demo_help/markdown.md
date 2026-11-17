How pages look
==============

Every page is an ordinary Markdown file. This one shows what can be used. Jump to [tables](#tables) or to [what a text screen cannot show](#what-a-text-screen-cannot-show).

## Text

Text can be **bold**, *italic* (shown underlined) or `code`. A line break needs two spaces at the end of the line,  
like this one. Special characters can be written with a backslash, as in \*this\*, or as entities, as in &copy; and &amp;.

## Lists

1. The first thing
2. The second thing, with items of its own
   - One of them
   - Another, with more
     - Nested as deep as you like
3. The third thing

## Quotes

> A block quote has a line down its left side.
>
> It can have several paragraphs, and a [link](index.md).

## Code

```python
def greet(name: str) -> str:
    return f"Hello, {name}!"
```

---

## Tables

| Key | What it does | Works in help |
|:----|:------------:|--------------:|
| F1 | Opens help for what has the focus, and goes to the index inside it | Yes |
| Esc | Closes help | Yes |
| F10 | Opens the menu bar | No |

## Headings

### The third level

#### The fourth level, and those below it

## What a text screen cannot show

An image shows its description instead: ![The Dasha Framework logo](logo.png).

HTML tags are <b>removed</b>, leaving the text inside them.

## Links

- To another page: [the index](index.md)
- To a heading on another page: [the second heading of the survey](survey.md#what-have-you-tried)
- To a page that is not there: [a missing page](missing.md)
- To the web: <https://example.com>
