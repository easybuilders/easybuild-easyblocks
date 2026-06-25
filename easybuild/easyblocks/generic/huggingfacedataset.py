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
from easybuild.tools.filetools import change_dir, clean_dir, dir_contains_files, mkdir, move_file
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
        _hf_snapshots_dir = os.path.join(
            _hf_home_dir,
            'hub',
            f'datasets--{self.cfg["hf_name"].replace("/", "--")}',
            'snapshots'
        )

        # Fill snapshosts dir (we're abusing the fallback for no-symlinks to simplify the logic)
        # https://huggingface.co/docs/huggingface_hub/guides/manage-cache#limitations
        mkdir(_hf_home_dir)
        mkdir(_hf_snapshots_dir, parents=True)

        for src_spec in self.cfg['data_sources']:
            move_file(src_spec['filename'],  os.path.join(_hf_snapshots_dir, src_spec['filename']))

        self.log.info(f"Successfully populated {_hf_snapshots_dir} from source files")

        # There might be a possibility to add an extra check with `hf cache verify`
        # https://huggingface.co/docs/huggingface_hub/package_reference/cli#hf-cache-verify

        # Build actual dataset
        py_script = '; '.join([
            "import datasets",
            f"""ds = datasets.load_dataset({
                ', '.join([
                    f"path='{self.cfg['hf_name']}'",
                    f"revision='{self.cfg['hf_revision']}'",
                    "verification_mode='all_checks'",
                    "num_proc=1",
                ])
            })""",
            f"ds.save_to_disk('{self._build_dataset_dir}')"
        ])

        cmd = " ".join([
            self.cfg['prebuildopts'],
            f'HF_HOME={_hf_home_dir} python -c "{py_script}"',
            self.cfg['buildopts'],
        ])
        run_shell_cmd(cmd)

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
                self.report_test_failure(f'HF_HOME populated on load_dataset({self._build_dataset_dir}) call')

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
