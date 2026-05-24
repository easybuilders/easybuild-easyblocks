##
# Copyright 2009-2026 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# https://github.com/easybuilders/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
##
"""
EasyBuild support for installing datasets

@author: Viktor Rehnberg (Chalmers University of Technology)
"""
import os
from tempfile import TemporaryDirectory

from easybuild.easyblocks.generic.dataset import Dataset
from easybuild.framework.easyconfig import CUSTOM, MANDATORY
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import change_dir, clean_dir, dir_contains_files, expand_glob_paths, find_glob_pattern
from easybuild.tools.filetools import mkdir, move_file, write_file
from easybuild.tools.run import run_shell_cmd


class HuggingFaceDataset(Dataset):
    '''Support for installing datasets from huggingface.co'''

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to Data easyblock."""
        extra_vars = Dataset.extra_options(extra_vars)
        extra_vars.update({
            'hf_name': [None, "Name of dataset on huggingface.co e.g. `uoft-cs/cifar10`", MANDATORY],
            'hf_revision': [None, "Version tag or commit hash on huggingface.co", MANDATORY],
            'extract_sources': [False, "Whether or not to extract data sources", CUSTOM],
        })
        return extra_vars

    @property
    def _build_dataset_dir(self):
        return os.path.join(self.builddir, "saved_dataset")

    def __init__(self, *args, **kwargs):
        '''Initialize HuggingFaceDataset-specific variables.'''
        super().__init__(*args, **kwargs)
        self.build_in_installdir = False

    def build_step(self):
        '''Build up cache_dir with dataset'''

        change_dir(self.builddir)
        _hf_home_dir = os.path.join(self.builddir, 'hf_home')
        _hf_cache_dir = os.path.join(self.builddir, 'hf_cache')
        _hf_cache_download_dir = os.path.join(_hf_cache_dir, 'downloads')

        mkdir(_hf_home_dir)
        mkdir(_hf_cache_dir)
        mkdir(_hf_cache_download_dir)

        # Prepare download directory of cache_dir
        def _hash_url_to_filename(url):
            return run_shell_cmd(
                f'python -c "import datasets; print(datasets.utils.file_utils.hash_url_to_filename(\'{url}\'))"'
            ).output.strip()

        for src_spec in self.cfg['data_sources']:
            _url = f"hf://datasets/{self.cfg['hf_name']}@{self.cfg['hf_revision']}/{src_spec['filename']}"
            hash_filename = os.path.join(
                _hf_cache_download_dir,
                _hash_url_to_filename(_url)
            )
            move_file(src_spec['filename'],  hash_filename)
            write_file(f"{hash_filename}.json", f'{{"url": "{_url}", "etag": null}}'.encode('utf-8'))

        self.log.info(f"Successfully populated {_hf_cache_download_dir} from source files")

        # Build actual dataset
        py_script = '; '.join([
            "import datasets",
            f"""ds = datasets.load_dataset({
                ', '.join([
                    f"path='{self.cfg['hf_name']}'",
                    f"revision='{self.cfg['hf_revision']}'",
                    f"cache_dir='{_hf_cache_dir}'",
                    "download_mode='reuse_cache_if_exists'",
                    "verification_mode='all_checks'",
                    "num_proc=1",
                ])
            })""",
            f"ds.save_to_disk('{self._build_dataset_dir}')"
        ])
        result = run_shell_cmd(f'HF_HOME={_hf_home_dir} python -c "{py_script}"')

        if any(
            line.startswith(f"Downloading data:")
            for line in result.output.splitlines()
        ):
            raise EasyBuildError('Unexpected download detected when loading dataset during build.')
        else:
            self.log.info(f"Successfully built dataset into {self._build_dataset_dir}")

    def test_step(self):
        '''Try loading dataset'''
        with TemporaryDirectory(prefix=self.builddir) as _hf_home_dir:
            py_script = '; '.join([
                "from datasets import load_from_disk",
                f"load_from_disk('{self._build_dataset_dir}')",
            ])
            run_shell_cmd(f'HF_HOME="{_hf_home_dir}" python -c "{py_script}"')

            if dir_contains_files(_hf_home_dir):
                report_test_failure(f'HF_HOME populated on load_dataset({dataset_dir}) call')

    def install_step(self):
        '''Move actual dataset directory to installdir'''
        change_dir(self.installdir)
        clean_dir(self.installdir)  # can't move dataset if dir already exists
        move_file(self._build_dataset_dir, self.installdir)
        if not dir_contains_files(self.installdir):
            raise EasyBuildError('Install directory is empty, something has gone wrong.')
        else:
            self.log.info("Successfully moved dataset from builddir")
        change_dir(self.installdir)

    def post_processing_step(self):
        # only for debugging
        change_dir(self.installdir)
        self.log.info("CWD = " + os.path.abspath(os.curdir))
        super().post_processing_step()
