from typing import Callable, Dict, Type, Optional, List # Optional, List を追加

from pydantic import BaseModel, ConfigDict


class RegisteredAction(BaseModel):
	"""Model for a registered action"""

	name: str
	description: str
	function: Callable
	param_model: Type[BaseModel]
	url_patterns: Optional[List[str]] = None # アクションが有効なURLパターンのリスト (Noneなら共通)

	model_config = ConfigDict(arbitrary_types_allowed=True)

	def prompt_description(self) -> str:
		"""Get a description of the action for the prompt"""
		skip_keys = ['title']
		s = f'{self.description}: \n'
		s += '{' + str(self.name) + ': '
		s += str(
			{
				k: {sub_k: sub_v for sub_k, sub_v in v.items() if sub_k not in skip_keys}
				for k, v in self.param_model.schema()['properties'].items()
			}
		)
		s += '}'
		return s


class ActionModel(BaseModel):
	"""Base model for dynamically created action models"""

	# this will have all the registered actions, e.g.
	# click_element = param_model = ClickElementParams
	# done = param_model = None
	#
	model_config = ConfigDict(arbitrary_types_allowed=True)

	def get_index(self) -> int | None:
		"""Get the index of the action"""
		# {'clicked_element': {'index':5}}
		params = self.model_dump(exclude_unset=True).values()
		if not params:
			return None
		for param in params:
			if param is not None and 'index' in param:
				return param['index']
		return None

	def set_index(self, index: int):
		"""Overwrite the index of the action"""
		# Get the action name and params
		action_data = self.model_dump(exclude_unset=True)
		action_name = next(iter(action_data.keys()))
		action_params = getattr(self, action_name)

		# Update the index directly on the model
		if hasattr(action_params, 'index'):
			action_params.index = index


class ActionRegistry(BaseModel):
	"""Model representing the action registry"""

	actions: Dict[str, RegisteredAction] = {}

	def get_prompt_description(self, allowed_actions: Optional[list[str]] = None) -> str:
		"""Get a description of actions for the prompt, optionally filtered by allowed_actions"""
		actions_to_describe = [
			action for name, action in self.actions.items()
			if allowed_actions is None or name in allowed_actions
		]
		return '\n'.join([action.prompt_description() for action in actions_to_describe])
