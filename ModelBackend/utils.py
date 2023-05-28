import json
import torch
from transformers import AutoModel, AutoTokenizer
from peft import PeftModel


class DeviceMap:
    __top_layer: str
    __layer_name: str
    __device_map: dict
    __total_layers: int
    __layers: int

    def __init__(self, model=None, config_path="./config/device_map_config.json"):
        with open(config_path, "r", encoding="utf-8") as file:
            config = json.load(file)[model]

        if config == None:
            self.__top_layer = ""
            self.__layer_name = ""
            self.__device_map = {"": "cuda:0"}
            self.__total_layers = 0
            self.__layers = 0
        else:
            self.__top_layer = config["top_layer"]
            self.__layer_name = config["layer_name"]
            self.__device_map = config["device_map"]
            self.__total_layers = config["total_layers"]
            self.__layers = config["layers"]

    def get(self):
        top_layer = self.__top_layer
        total_layers = self.__total_layers
        layer_name = self.__layer_name
        layers = self.__layers
        device_map = self.__device_map

        world_size = torch.cuda.device_count()

        free_gpu_mem = []
        for i in range(world_size):
            torch.cuda.set_device(i)
            free_gpu_mem.append(torch.cuda.mem_get_info()[0])

        min_id = min(enumerate(free_gpu_mem), key=lambda x: x[1])[0]
        max_id = max(enumerate(free_gpu_mem), key=lambda x: x[1])[0]

        totol_mem = sum(free_gpu_mem)

        world_layers = {
            id: int(round(total_layers * (mem / totol_mem)))
            for id, mem in enumerate(free_gpu_mem)
        }

        diff = total_layers - sum(world_layers.values())
        world_layers[max_id if diff > 0 else min_id] += diff

        cnt = total_layers - layers
        gpu_id = 0

        for i in range(layers):
            if cnt < world_layers[gpu_id]:
                cnt += 1
            else:
                gpu_id += 1
                cnt = 1
            device_map[f"{top_layer}.{layer_name}.{i}"] = f"cuda:{gpu_id}"

        return device_map

    def peft(self):
        prefix = "base_model.model"
        device_map = self.get()
        perf_device_map = {"": "cuda:0"}
        for k, v in device_map.items():
            perf_device_map[f"{prefix}.{k}"] = v
        return perf_device_map


class ModelLoader:
    def __init__(self, model_name: str = None):
        self.model = AutoModel.from_pretrained(
            model_name, trust_remote_code=True, device_map=DeviceMap(model_name).get()
        )
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name, trust_remote_code=True
        )

    def peft(self, peft_name: str = None):
        self.model = PeftModel.from_pretrained(self.model, peft_name)

    def generate_prompt(self, instruction: str = None, input: str = None):
        return f"{instruction}\n\nInput:\n{input}"

    def evaluate(self, instruction: str = None, input: str = None):
        prompt = self.generate_prompt(instruction, input)
        with torch.no_grad():
            token = self.tokenizer.encode(prompt, return_tensors="pt")
            output = self.model.generate(input_ids=token)
            answer = self.tokenizer.decode(output[0])
        return answer
