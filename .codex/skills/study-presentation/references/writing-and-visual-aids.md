# Writing and visual aids for report readers

Use when drafting a report's opening, defining a group, or deciding whether a
definition needs a picture. Sources consulted on 2026-11-01. The target reader is a
magazine reader who never joined the discussion; the page supplies all its context.

## Order

- Lead with the answer and put detail after it
  ([inverted pyramid](https://www.nngroup.com/articles/inverted-pyramid/)). Write the
  Big Idea as one sentence before choosing any component.
- A heading says what the reader will see, not the topic
  ([Datawrapper on readers' time](https://www.datawrapper.de/blog/readers-time)).

## Terms

- Define a term where it first appears, not in a glossary page.
- Introduce the fewest terms the finding needs. If an everyday phrase exists, use it
  instead of jargon ([Digital.gov: avoid jargon](https://digital.gov/guides/plain-language/principles/avoid-jargon)).
- Use one example for the whole page, with concrete numbers (start price 100, so a
  threshold becomes 62.5 and 40, and the target 200).
- For an approximate number write the everyday form and put the exact count in
  brackets: 約一年（240 個交易日）. Do not let 240 / 250 / 252 read as meaningful differences.

## Choosing the aid

| What needs explaining                                      | Aid                                                            |
| ---------------------------------------------------------- | -------------------------------------------------------------- |
| An everyday word, or a term used once                      | None, or a half-sentence gloss                                 |
| A threshold or multiple                                    | One sentence plus the numbers of the shared example            |
| Several price levels against one base                      | Small static number line, `aria-hidden`, text complete         |
| A window and the order of events                           | Static timeline with day ranges                                |
| A price pattern                                            | Small static sketch; 2-3 frames only if the steps matter       |
| A change the reader triggers, or the action is the concept | Animation of at most 250 ms, honoring `prefers-reduced-motion` |
| Quantities that are compared                               | Shared zero-baseline chart                                     |

Animation is usually no better than an equal static picture; it helps only when the
change itself is the content ([Tversky et al. 2002](https://hci.stanford.edu/courses/cs448b/papers/Tversky_AnimationFacilitate_IJHCS02.pdf);
[Höffler & Leutner 2007](https://www.leibniz-ipn.de/en/research/publications/instructional-animation-versus-static-pictures-a-meta-analysis)).
Delete an aid that repeats the adjacent sentence and adds no new relation.

## Tone

State a limit only when it changes how the nearby number is read, as a fact about
population, window or data. GOV.UK warning text is for consequences of the reader's own
action ([component](https://design-system.service.gov.uk/components/warning-text/));
do not use it for research limits.

| Avoid                                        | Write                                                             |
| -------------------------------------------- | ----------------------------------------------------------------- |
| 10.2% 對 22.5%；這是歷史關聯，不是訊號造成。 | 主要限制：同一段歷史、尚無獨立驗證期。                            |
| 反面提醒                                     | 同一訊號也常出現在最後翻倍的股票                                  |
| 不能解讀為第20日賣出會錯過的比例。           | 這批事件看的是到翻倍為止的整段期間，訊號可能在第20日之後才出現。  |
| 觀察到的關係不能直接轉成交易規則             | 定義與限制：同一段歷史、未模擬買賣                                |
| 僅供參考／請勿照做                           | Delete; the stated population and window already limit the claim. |
