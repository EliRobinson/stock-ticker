# Stock Ticker

A personal research tool for studying S&P 500 companies: their prices over time, what the user thinks about them, and questions answered by AI.

## Language

**Company**:
An issuer in the Constituent List, identified by its SEC CIK. One Company can trade under several Listings.
_Avoid_: stock, security, ticker (as the name of the thing)

**Listing**:
One ticker symbol of a Company, such as GOOGL or GOOG for Alphabet. Prices belong to a Listing.
_Avoid_: symbol, share class (in UI copy)

**Constituent List**:
The S&P 500 membership as it is today. The past membership is not modeled, so companies that left the index are absent (survivorship bias).
_Avoid_: index, universe

**Trading Day**:
A date on which the US stock market held a session, dated in New York time. Weekends, holidays, and closures are not Trading Days.
_Avoid_: business day

**Daily Bar**:
One Listing's open, high, low, close, and volume for one Trading Day, stored both as traded and as adjusted.
_Avoid_: candle, tick, price row

**Adjusted Close**:
A close price rescaled for later splits and dividends, so that moves across time compare fairly. Charts and percent changes use it.
_Avoid_: close (without a qualifier)

**Quote**:
The latest observed price of one Listing, with the time it was observed.
_Avoid_: live price, ticker

**Stale Quote**:
A Quote older than expected while the market is open. It is shown with its age, never as current.

**Market Cap**:
A Company's value on a Trading Day: the as-traded close of its pricing Listing × the Company's total shares outstanding as known on that day (from the latest filing already filed by then), corrected for splits between that filing and the day. For a Company with several share classes it is approximate.
_Avoid_: market value, size

**Event**:
A dated fact about a Company taken from a source, such as a stock split or an SEC filing. Events are recorded, never written by the user.
_Avoid_: annotation, note

**Note**:
The user's written thought, anchored to one date or one date range, and optionally to one Company. A Note with no Company is about the whole market.
_Avoid_: comment, annotation (in UI copy), journal entry

## Relationships

- A **Company** has one or more **Listings** and a **Market Cap** on each **Trading Day**.
- A **Listing** has many **Daily Bars** and at most one current **Quote**.
- A **Company** has many **Events**.
- A **Note** covers one date or one date range, and refers to zero or one **Company**.

## Example dialogue

> **Dev:** "GOOGL fell 5% on that day. Is that Alphabet's Market Cap falling 5%?"
> **Domain expert:** "Yes. Market Cap is for the Company and is priced from one Listing (GOOGL), times all of Alphabet's shares. That is why it is marked approximate: GOOG may have closed a little differently."

## Flagged ambiguities

- "Note" versus "Event": a Note is the user's opinion, while an Event is a sourced fact. Both show as chart markers but are never merged.
