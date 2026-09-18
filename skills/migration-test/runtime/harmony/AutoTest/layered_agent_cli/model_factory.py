import random
from typing import Any, Dict, List, Tuple

from agents.models.interface import Model
from agents.model_settings import ModelSettings
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncAzureOpenAI, AsyncOpenAI
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage

from ..logger import logger


class MultiProviderModel(Model):
    """Wrapper for multiple models with fallback strategy."""

    def __init__(self, models_data: list[tuple[Any, ModelSettings]]):
        self.models_data = []
        for idx, (model, settings) in enumerate(models_data):
            # Tag the model with an internal ID for debugging/logging purposes
            try:
                setattr(model, '_provider_id', idx + 1)
            except:
                pass
            self.models_data.append((model, settings))

        if not self.models_data:
            raise ValueError("No models provided to MultiProviderModel")

    @staticmethod
    def _has_actionable_output(result) -> bool:
        output = getattr(result, 'output', None) or []
        for item in output:
            if isinstance(item, ResponseFunctionToolCall):
                return True
        for item in output:
            if isinstance(item, ResponseOutputMessage):
                for content in item.content:
                    text = content.text
                    if "任务结果" not in text and "通过" not in text:
                        logger.info(f"大模型没有输出工具调用，且输出内容不是任务结果，不符合。输出如下：\n{text}")
                        return False
                return True

        return False


    async def get_response(self, *args, **kwargs):
        last_exception = None
        # Create a shallow copy and shuffle it for this specific call to distribute load
        current_models = list(self.models_data)
        random.shuffle(current_models)

        for model, settings in current_models:
            try:
                model_name = getattr(model, 'model', 'unknown')
                provider_id = getattr(model, '_provider_id', 'unknown')
                logger.info(f"Attempting to use decision model #{provider_id}: {model_name}")

                if 'settings' in kwargs:
                    kwargs['settings'] = settings
                elif 'model_settings' in kwargs:
                    kwargs['model_settings'] = settings
                result = None
                exception = None
                for _ in range(3):
                    try:
                        result = await model.get_response(*args, **kwargs)
                        if self._has_actionable_output(result):
                            break
                        output_types = [
                            getattr(item, 'type', type(item).__name__)
                            for item in getattr(result, 'output', [])
                        ]
                        logger.warning(
                            f"No actionable model output. output types: {output_types}. Need to retry...")
                    except Exception as e:
                        exception = e
                        logger.warning(f"Model #{provider_id} failed. error: {e}. Retrying...")
                else:
                    if exception:
                        raise exception
                    raise RuntimeError("Model failed to return valid output after 3 retries")

                return result
            except Exception as e:
                model_name = getattr(model, 'model', 'unknown')
                provider_id = getattr(model, '_provider_id', 'unknown')
                logger.warning(
                    f"Model #{provider_id} (name: {model_name}) method 'get_response' failed: {e}. Switching to next model...")
                last_exception = e

        # If all models failed
        if last_exception:
            logger.error(f"All models failed. Last error: {last_exception}")
            raise last_exception
        return None

    def stream_response(self, *args, **kwargs):
        last_exception = None
        # Create a shallow copy and shuffle it for this specific call to distribute load
        current_models = list(self.models_data)
        random.shuffle(current_models)

        for model, settings in current_models:
            try:
                model_name = getattr(model, 'model', 'unknown')
                provider_id = getattr(model, '_provider_id', 'unknown')
                logger.info(f"Attempting to use decision model #{provider_id} (streaming): {model_name}")

                if 'settings' in kwargs:
                    kwargs['settings'] = settings
                elif 'model_settings' in kwargs:
                    kwargs['model_settings'] = settings

                return model.stream_response(*args, **kwargs)

            except Exception as e:
                model_name = getattr(model, 'model', 'unknown')
                provider_id = getattr(model, '_provider_id', 'unknown')
                logger.warning(
                    f"Model #{provider_id} (name: {model_name}) method 'stream_response' failed: {e}. Switching to next model...")
                last_exception = e

        # If all models failed
        if last_exception:
            logger.error(f"All models failed. Last error: {last_exception}")
            raise last_exception
        return None


def create_client_from_dict(model_config: dict):
    base_url = model_config.get("base_url", "")
    api_key = model_config.get("api_key", "")
    api_version = model_config.get("api_version", "")
    temperature = model_config.get("temperature", 0.7)
    top_p = model_config.get("top_p", 0.9)
    frequency_penalty = model_config.get("frequency_penalty", 0.0)
    max_token = model_config.get("max_token", 8192)

    if api_version:
        client = AsyncAzureOpenAI(
            azure_endpoint=base_url,
            api_version=api_version,
            api_key=api_key,
            default_headers={
                "X-TT-LOGID": ""
            },
            timeout=600,
            max_retries=3
        )

        model_settings = ModelSettings(
            temperature=temperature,
            top_p=top_p,
            frequency_penalty=frequency_penalty,
            max_tokens=max_token,
            extra_body={
                "enable_thinking": True
            }
        )

    else:
        # Default OpenAI setup
        client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=600,
            max_retries=3
        )

        model_settings = ModelSettings(
            temperature=temperature,
            top_p=top_p,
            frequency_penalty=frequency_penalty,
            max_tokens=max_token,
        )

    return client, model_settings


def create_multi_model(models_config: List[Dict[str, Any]]) -> Tuple[MultiProviderModel, ModelSettings]:
    """
    Create a MultiProviderModel instance from a list of model configurations.
    Returns the MultiProviderModel instance and the default settings (from the first model).
    """
    models_data = []

    for model_conf in models_config:
        try:
            client, settings = create_client_from_dict(model_conf)
            model_instance = OpenAIChatCompletionsModel(
                model=model_conf.get("name", ""),
                openai_client=client,
            )
            models_data.append((model_instance, settings))
        except Exception as e:
            logger.error(f"Failed to initialize model from config: "
                         f"{model_conf.get('name', 'unknown')}, error: {e}")

    if not models_data:
        raise ValueError("No valid models found in configuration.")

    multi_model = MultiProviderModel(models_data)

    # Use the settings of the first model as default/placeholder
    default_settings = models_data[0][1]

    return multi_model, default_settings
