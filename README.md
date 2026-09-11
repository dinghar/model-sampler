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

## Roadmap

1. Use OpenRouter to easily support a variety of models.
2. Don't make the user select the models and configs to try. The user should pass in a model to start with, and the tool finds the cheapest model with comparable performance.