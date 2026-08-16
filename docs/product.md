# What Is Yuzu?

**Status:** Current product compass  
**Date:** 2026-07-26

> Yuzu is a private, persistent digital entity.
>
> The primary experience is an ongoing conversation between Bani and Yuzu.
> Everything else exists only to support that relationship.

## Primary goals

- Conversation feels immediate, readable, and natural.
- Yuzu feels continuous across sessions.
- Memory supports the conversation without becoming a database interface.
- Tools feel like things Yuzu can do, not a second application the user must operate.
- The interface stays quiet enough for the conversation to remain the subject.
- The user can always tell whether Yuzu is waiting, thinking, using a tool, or finished.
- Configuration remains available without competing with the conversation.

## Non-goals

- Becoming a ChatGPT or Gemini clone.
- Showing every capability on the primary surface.
- Turning memory, providers, and generation parameters into the product identity.
- Adding visual effects merely to make the interface look modern.
- Supporting every provider or feature at the cost of clarity.
- Introducing architecture, abstraction, or navigation that does not improve the lived conversation.

## Product hierarchy

1. **Conversation** — the product.
2. **Yuzu's current state** — useful context while the conversation is happening.
3. **Sessions and memory** — continuity mechanisms, available when needed.
4. **Tools and generated media** — actions that appear in context.
5. **Configuration and provider controls** — maintenance surfaces, deliberately secondary.
6. **About and implementation details** — reference material, not primary navigation.

## Interface principles

1. The default destination should feel like entering a conversation, not opening an administration dashboard.
2. The interface should visualize runtime state rather than expose the machinery behind it.
3. Yuzu's identity should be visible but quiet; the session should not feel like a generic anonymous chat room.
4. Assistant messages should read as conversation first, not as repeated cards in a component gallery.
5. User messages may be visually distinct, but neither side should dominate through decoration.
6. Tool activity should be understandable and compact; details can be expanded when relevant.
7. Session switching should preserve the feeling of continuity rather than feel like changing applications.
8. Configuration should explain consequences in human terms and stay out of the way during normal use.
9. Motion should communicate state or continuity. Decorative motion is not a substitute for hierarchy.
10. Every new element must justify its presence by improving conversation, continuity, comprehension, or control.

## Definition of success

A person opening Yuzu should understand within a few seconds:

- who they are talking to;
- where the current conversation is;
- where to type;
- whether Yuzu is responding or using a tool;
- how to reach another session or configuration without losing the conversational context.

If the first impression instead asks the person to choose between application modules, inspect system status, or understand provider terminology, the interface is serving the implementation instead of Yuzu.
