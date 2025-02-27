# Based on https://github.com/c0zaut/ez-er-rkllm-toolkit/blob/5d752cfa008071cc1f50a43dbe06e28b65ae5312/docker-noninteractive/noninteractive_pipeline.py
from enum import Enum
from huggingface_hub import auth_check
from huggingface_hub import HfApi
from huggingface_hub import login
from huggingface_hub import ModelCard
from huggingface_hub import snapshot_download
from huggingface_hub import whoami
from huggingface_hub.utils import GatedRepoError  # type: ignore
from huggingface_hub.utils import RepositoryNotFoundError  # type: ignore
from pathlib import Path
from typing import List
from typing import Union
import inquirer
import os
import shutil
import typer


class RKLLMRemotePipeline:
    def __init__(
        self,
        model_id="",
        lora_id="",
        platform="rk3588",
        qtype="w8a8",
        hybrid_rate="0.0",
        library_type="HF",
        optimization=1,
    ):
        """
        Initialize primary values for pipeline class.

        :param model_id: HuggingFace repository ID for model (required)
        :param lora_id: Same as model_id, but for LoRA (optional)
        :param platform: CPU type of target platform. Must be rk3588 or rk3576
        :param optimization: 1 means "optimize model" and 0 means "don't optimize" - may incrase performance,
            at the expense of accuracy
        :param qtype: either a string or list of quantization types
        :param hybrid_rate: block(group-wise quantization) ratio, whose value is between
            0 and 1, 0 indicating the disable of mixed quantization
        """
        self.model_id = model_id
        self.lora_id = lora_id
        self.platform = platform
        self.qtype = qtype
        self.hybrid_rate = hybrid_rate
        self.library_type = library_type
        self.optimization = optimization

    @staticmethod
    def mkpath(path):
        """
        HuggingFace Hub will just fail if the local_dir you are downloading to does not exist
        RKLLM will also fail to export if the directory does not already exist.

        :param paths: a list of paths (as strings) to check and create
        """
        try:
            if not os.path.exists(path):
                os.makedirs(path)
                print(f"mkdir'd {path}")
            else:
                print(f"Path {path} already exists! Great job!")
        except RuntimeError as e:
            print(f"Can't create paths for importing and exporting model.\n{e}")

    @staticmethod
    def cleanup_models(path=Path("./models")):
        print(f"Cleaning up model directory...")
        shutil.rmtree(path)

    def build_vars(self):
        if self.platform == "rk3588":
            self.npu_cores = 3
        elif self.platform == "rk3576":
            self.npu_cores = 2
        self.dataset = None
        self.qparams = None
        self.device = "cpu"
        self.model_name = self.model_id.split("/", 1)[1]
        self.model_dir = f"./models/{self.model_name}/"
        self.name_suffix = f"{self.platform}-{self.qtype}-opt-{self.optimization}-hybrid-ratio-{self.hybrid_rate}"
        if self.lora_id == "":
            self.lora_name = None
            self.lora_dir = None
            self.lorapath = None
            self.export_name = f"{self.model_name}-{self.name_suffix}"
            self.export_path = f"./models/{self.model_name}-{self.platform}/"
        else:
            self.lora_name = self.lora_id.split("/", 1)[1]
            self.lora_dir = f"./models/{self.lora_name}/"
            self.export_name = f"{self.model_name}-{self.lora_name}-{self.name_suffix}"
            self.export_path = (
                f"./models/{self.model_name}-{self.lora_name}-{self.platform}/"
            )
        self.rkllm_version = "1.1.4"

    def remote_pipeline_to_local(self):
        """
        Full conversion pipeline
        Downloads the chosen model from HuggingFace to a local destination, so no need
        to copy from the local HF cache.
        """
        print(f"Checking if {self.model_dir} and {self.export_path} exist...")
        self.mkpath(self.model_dir)
        self.mkpath(self.export_path)

        print(
            f"Loading base model {self.model_id} from HuggingFace and downloading to {self.model_dir}"
        )
        self.modelpath = snapshot_download(
            repo_id=self.model_id, local_dir=self.model_dir
        )

        if self.lora_id == None:
            print(f"LoRA is {self.lora_id} - skipping download")
        else:
            print(
                f"Downloading LoRA: {self.lora_id} from HuggingFace to {self.lora_dir}"
            )
            try:
                self.lorapath = snapshot_download(
                    repo_id=self.lora_id, local_dir=self.lora_dir
                )
            except:
                print(f"Downloading LoRA failed. Omitting from export.")
                self.lorapath == None

        print("Initializing RKLLM class...")
        from rkllm.api import RKLLM  # type: ignore

        self.rkllm = RKLLM()

        if self.library_type == "HF":
            print(f"Have to load model for each config")
            status = self.rkllm.load_huggingface(
                model=self.modelpath, model_lora=self.lorapath, device=self.device
            )
            if status != 0:
                raise RuntimeError(f"Failed to load model: {status}")
            else:
                print(f"{self.model_name} loaded successfully!")
        elif self.library_type == "GGUF":
            print(f"Have to load model for each config")
            status = self.rkllm.load_gguf(model=self.modelpath)
            if status != 0:
                raise RuntimeError(f"Failed to load model: {status}")
            else:
                print(f"{self.model_name} loaded successfully!")
        else:
            print("Model must be of type HF (HuggingFace) or GGUF.")
            raise RuntimeError("Must be something wrong with the selector! Try again!")

        print(
            f"Building {self.model_name} with {self.qtype} quantization and optimization level {self.optimization}"
        )
        status = self.rkllm.build(
            optimization_level=self.optimization,
            quantized_dtype=self.qtype,
            target_platform=self.platform,
            num_npu_core=self.npu_cores,
            extra_qparams=self.qparams,
            dataset=self.dataset,
        )
        if status != 0:
            raise RuntimeError(f"Failed to build model: {status}")
        else:
            print(f"{self.model_name} built successfully!")

        status = self.rkllm.export_rkllm(f"{self.export_path}{self.export_name}.rkllm")
        if status != 0:
            raise RuntimeError(f"Failed to export model: {status}")
        else:
            print(f"{self.model_name} exported successfully to {self.export_path}!")


# Don't trust super().__init__ here
class HubHelpers:
    def __init__(self, platform, model_id, lora_id, qtype, rkllm_version):
        """
        Collection of helpers for interacting with HuggingFace.
        Due to some weird memory leak-y behaviors observed, would rather pass down
        parameters from the pipeline class then try to do something with super().__init__

        :param platform: CPU type of target platform. Must be rk3588 or rk3576
        :param model_id: HuggingFace repository ID for model (required)
        :param lora_id: Same as model_id, but for LoRA (optional)
        :param rkllm_version: version of RKLLM used for conversion.
        """
        self.model_id = model_id
        self.lora_id = lora_id
        self.platform = platform
        self.qtype = qtype
        self.models = {"base": model_id, "lora": lora_id}
        self.rkllm_version = rkllm_version
        self.home_dir = os.environ["HOME"]
        # Use Rust implementation of transfer for moar speed
        os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"

    @staticmethod
    def repo_check(model):
        """
        Checks if a HuggingFace repo exists and is gated
        """
        try:
            auth_check(model)
        except GatedRepoError:
            # Handle gated repository error
            print(
                f"{model} is a gated repo.\nYou do not have permission to access it.\n \
                  Please authenticate.\n"
            )
        except RepositoryNotFoundError:
            # Handle repository not found error
            print(f"{model} not found.")
        else:
            print(f"Model repo {model} has been validated!")
            return True

    def login_to_hf(self):
        """
        Helper function to authenticate with HuggingFace.
        Necessary for downloading gated repositories, and uploading.
        """
        self.token_path = f"{self.home_dir}/.cache/huggingface/token"
        if os.path.exists(self.token_path):
            self.token_file = open(self.token_path, "r")
            self.hf_token = self.token_file.read()
        else:
            self.hf_input = [
                inquirer.Text(
                    "token", message="Please enter your Hugging Face token", default=""
                )
            ]
            self.hf_token = inquirer.prompt(self.hf_input)["token"]
        try:
            login(token=self.hf_token)
        except Exception as e:
            print(
                f"Login failed: {e}\nGated models will be inaccessible, and you "
                + "will not be able to upload to HuggingFace."
            )
        else:
            print("Logged into HuggingFace!")
        self.hf_username = whoami(self.hf_token)["name"]
        print(self.hf_username)

    def build_card(self, export_path):
        """
        Inserts text into the README.md file of the original model, after the model data.
        Using the HF built-in functions kept omitting the card's model data,
        so gonna do this old school.
        """
        self.model_name = self.model_id.split("/", 1)[1]
        self.card_in = ModelCard.load(self.model_id)
        self.card_out = export_path + "README.md"
        self.template = (
            f"---\n"
            + f"{self.card_in.data.to_yaml()}\n"
            + f"---\n"
            + f"# {self.model_name}-{self.platform.upper()}-{self.rkllm_version}\n\n"
            + f"This version of {self.model_name} has been converted to run on the {self.platform.upper()} NPU using {self.qtype} quantization.\n\n"
            + f"This model has been optimized with the following LoRA: {self.lora_id}\n\n"
            + f"Compatible with RKLLM version: {self.rkllm_version}\n\n"
            + f"## Useful links:\n"
            + f"[Official RKLLM GitHub](https://github.com/airockchip/rknn-llm) \n\n"
            + f"[RockhipNPU Reddit](https://reddit.com/r/RockchipNPU) \n\n"
            + f"[EZRKNN-LLM](https://github.com/Pelochus/ezrknn-llm/) \n\n"
            + f"Pretty much anything by these folks: [marty1885](https://github.com/marty1885) and [happyme531](https://huggingface.co/happyme531) \n\n"
            + f"Converted using https://github.com/c0zaut/ez-er-rkllm-toolkit \n\n"
            + f"# Original Model Card for base model, {self.model_name}, below:\n\n"
            + f"{self.card_in.text}"
        )
        try:
            ModelCard.save(self.template, self.card_out)
        except RuntimeError as e:
            print(f"Runtime Error: {e}")
        except RuntimeWarning as w:
            print(f"Runtime Warning: {w}")
        else:
            print(f"Model card successfully exported to {self.card_out}!")
            c = open(self.card_out, "r")
            print(c.read())
            c.close()

    def upload_to_repo(self, model, import_path, export_path):
        self.hf_api = HfApi(token=self.hf_token)
        self.repo_id = (
            f"{self.hf_username}/{model}-{self.platform}-{self.rkllm_version}"
        )

        print(f"Creating repo if it does not already exist")
        try:
            self.repo_url = self.hf_api.create_repo(exist_ok=True, repo_id=self.repo_id)
        except:
            print(f"Create repo for {model} failed!")
        else:
            print(f"Repo created! URL: {self.repo_url}")

        print(f"Generating model card and copying configs")
        self.build_card(export_path)
        self.import_path = Path(import_path)
        self.export_path = Path(export_path)
        shutil.copytree(
            self.import_path,
            self.export_path,
            ignore=shutil.ignore_patterns(
                "*.safetensors", "*.pt*", "*.bin", "*.gguf", "README*"
            ),
            copy_function=shutil.copy2,
            dirs_exist_ok=True,
        )
        self.hf_api.upload_folder(repo_id=self.repo_id, folder_path=export_path)


class Platform(str, Enum):
    rk3588 = "rk3588"
    rk3576 = "rk3576"


class QTypesRk3588(str, Enum):
    w8a8 = "w8a8"
    w8a8_g128 = "w8a8_g128"
    w8a8_g256 = "w8a8_g256"
    w8a8_g512 = "w8a8_g512"


class QTypesRk3576(str, Enum):
    w8a8 = "w8a8"
    w4a16 = "w4a16"
    w4a16_g32 = "w4a16_g32"
    w4a16_g64 = "w4a16_g64"
    w4a16_g128 = "w4a16_g128"


cli = typer.Typer()


@cli.command(no_args_is_help=True)
def convert(
    model_ids: List[str] = typer.Argument(..., help="HuggingFace model IDs"),
    qtypes: List[str] = typer.Option(default=["w8a8"], help="Quantization types"),
    hybrid_rates: List[float] = typer.Option(default=[0.0], help="Hybrid rates"),
    optimization: bool = typer.Option(default=True, help="Optimization level"),
    platform: Platform = typer.Option(default=Platform.rk3588, help="Target platform"),
):
    # Validate
    if platform == "rk3588":
        assert all(QTypesRk3588(qtype) in QTypesRk3588 for qtype in qtypes)
    elif platform == "rk3576":
        assert all(QTypesRk3576(qtype) in QTypesRk3576 for qtype in qtypes)
    assert all(0 <= hybrid_rate <= 1 for hybrid_rate in hybrid_rates)
    # Convert
    for model in model_ids:
        for qtype in qtypes:
            for hybrid_rate in hybrid_rates:
                rk = RKLLMRemotePipeline(
                    model_id=f"{model}",
                    lora_id="",
                    platform=f"{platform}",
                    qtype=f"{qtype}",
                    hybrid_rate=f"{hybrid_rate}",
                    library_type="HF",
                    optimization=1 if optimization else 0,
                )
                rk.build_vars()
                hf = HubHelpers(
                    platform=rk.platform,
                    model_id=model,
                    lora_id=rk.lora_id,
                    qtype=qtype,
                    rkllm_version=rk.rkllm_version,
                )
                hf.login_to_hf()
                hf.repo_check(rk.model_id)
                try:
                    rk.remote_pipeline_to_local()
                    hf.upload_to_repo(
                        model=rk.model_name,
                        import_path=rk.model_dir,
                        export_path=rk.export_path,
                    )
                except RuntimeError as e:
                    print(f"Model conversion failed: {e}")


def main() -> None:
    cli()
