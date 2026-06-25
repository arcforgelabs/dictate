# Intent

Dictate turns speech into usable text without making the user manage a
heavyweight editor, recorder, or meeting tool. It should make spoken input feel
fast enough for everyday writing, prompts, messages, and email, while also
supporting reliable transcript-first capture for longer conversations.

The current product is a desktop daily driver, but the intent is not limited to
desktop. Dictate should be able to follow the user across practical capture
contexts, including an on-the-run mobile experience, while preserving the same
core promise: speak naturally, get an accurate transcript, and decide where that
text belongs afterward.

Dictate should prefer local-first operation where that gives the best user
experience, privacy, and reliability, especially on desktop. When hosted models
are the better fit, the product should make that explicit and handle sensitive
transcript text carefully. Advanced BYO-key provider configuration can remain
available through CLI configuration, but the main Dictate Pro product should
handle hosted access for the user through account entitlements rather than
exposing provider backend switching as a primary app workflow.
