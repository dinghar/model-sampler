# Model Sampler

Sample inference to different models and compare performance.

## Background

You probably don't need to use Fable. But how small of a model will work?

If your goal is to save money, why burn tokens on heavy eval pipelines?

## Principles

- Use real customer traffic for evals
- Use explicit user success metrics for scoring
- Save $$$

## How It Works

- Define a `call site`. This is a specific LLM interaction surface in your app.
- Assign a user a `scope id`. This is used to identify a single unit of interaction, tying the user's interactions and success metric.
- Define models or model configurations and sample rate.
- See how performance stacks up.

## Demo

In the demo video, a user asks a chatbot to solve various NYT Pangrams and gives a thumbs up or down if the answer is correct. Inference is sampled between Sonnet 5 with Thinking enabled or disabled.

https://github.com/user-attachments/assets/af280340-d35a-4310-9da6-2f673b2dfa90

<img width="1104" height="447" alt="Screenshot 2026-09-11 at 10 32 56 AM" src="https://github.com/user-attachments/assets/ae5e4d79-2749-4ec6-b2c1-d467889e7169" />

## Roadmap

1. Use OpenRouter to easily support a variety of models.
2. Don't make the user select the models and configs to try. The user should pass in a model to start with, and the tool finds the cheapest model with comparable performance.
