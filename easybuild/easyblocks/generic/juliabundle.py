##
# Copyright 2022-2026 Vrije Universiteit Brussel
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
EasyBuild support for bundles of Julia packages, implemented as an easyblock

@author: Alex Domingo (Vrije Universiteit Brussel)
@author: Davide Grassano (CECAM, EPFL)
"""
import os
import subprocess
import sys
import tempfile
import time
import toml
from collections import defaultdict

from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.easyblocks.generic.juliapackage import EXTS_FILTER_JULIA_PACKAGES, JuliaPackage


HAS_REQUESTS = False
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    pass


class JuliaBundle(Bundle, JuliaPackage):
    """
    Bundle of JuliaPackages: install Julia packages as extensions in a bundle
    Defines custom sanity checks and module environment
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Easyconfig parameters specific to bundles of Julia packages."""
        if extra_vars is None:
            extra_vars = {}
        # combine custom easyconfig parameters of Bundle & JuliaPackage
        extra_vars = Bundle.extra_options(extra_vars)
        return JuliaPackage.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialize JuliaBundle easyblock."""
        super().__init__(*args, **kwargs)

        self.cfg['exts_defaultclass'] = 'JuliaPackage'
        self.cfg['exts_filter'] = EXTS_FILTER_JULIA_PACKAGES

        # need to disable templating to ensure that actual value for exts_default_options is updated...
        with self.cfg.disable_templating():
            # set default options for extensions according to relevant top-level easyconfig parameters
            jlpkg_keys = JuliaPackage.extra_options().keys()
            for key in jlpkg_keys:
                if key not in self.cfg['exts_default_options']:
                    self.cfg['exts_default_options'][key] = self.cfg[key]

            # Sources of Julia packages are commonly distributed from GitHub repos.
            # By default, rename downloaded tarballs to avoid name collisions on
            # packages sharing the same version string
            if 'sources' not in self.cfg['exts_default_options']:
                self.cfg['exts_default_options']['sources'] = [
                    {
                        'download_filename': 'v%(version)s.tar.gz',
                        'filename': '%(name)s-%(version)s.tar.gz',
                    }
                ]

        self.log.info("exts_default_options: %s", self.cfg['exts_default_options'])

    def prepare_step(self, *args, **kwargs):
        """Prepare for installing bundle of Julia packages."""
        super().prepare_step(*args, **kwargs)

    def install_step(self):
        """Prepare installation environment and dd all dependencies to project environment."""
        self.prepare_julia_env()
        self.include_pkg_dependencies()

    def sanity_check_step(self, *args, **kwargs):
        """Custom sanity check for bundle of Julia packages"""
        custom_paths = {
            'files': [],
            'dirs': [os.path.join('packages', self.name)],
        }
        super().sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self, *args, **kwargs):
        """Custom module environment from JuliaPackage"""
        return super().make_module_extra(*args, **kwargs)


IsJuliaPackage = type('IsJuliaPackage', (), {})  # sentinel value to indicate package is part of Julia stdlib


def get_git_exec():
    """Get path to git executable"""
    return subprocess.run(['which', 'git'], capture_output=True, text=True).stdout.strip()


def get_julia_exec():
    """Get path to Julia executable"""
    return subprocess.run(['which', 'julia'], capture_output=True, text=True).stdout.strip()


def check_needed_tools():
    """Check if needed dependencies and executables are available for determining source URLs from git tree SHA1"""
    julia_exec = get_julia_exec()
    git_exec = get_git_exec()

    if not julia_exec:
        print("WARNING: No Julia executable found in PATH, cannot determine if packages are part of standard library")
    else:
        print(f"Found Julia executable at: {julia_exec}")

    if not git_exec:
        print(
            "WARNING: No git executable found in PATH, cannot determine commit from git tree SHA1 for packages "
            "hosted on GitLab"
            )
    else:
        print(f"Found git executable at: {git_exec}")

    if not HAS_REQUESTS:
        print("WARNING: requests library not available, cannot fetch package data from General registry")


def get_commit_from_git_tree_sha1(repo, git_tree_sha1):
    """"Determine commit corresponding to git tree SHA1 by cloning the repo and searching the git log"""
    git_exec = get_git_exec()
    if not git_exec:
        return None

    commit = None

    with tempfile.TemporaryDirectory() as tmpdir:
        print(
            f'Attempting to determine commit for git tree SHA1 by cloning repo {repo} '
            f'into temporary directory {tmpdir}...'
        )
        try:
            print('Running git clone command...')
            subprocess.run(
                [git_exec, 'clone', repo, tmpdir],
                capture_output=True, text=True, check=True
            )
            print('Running git log command to find commit for git tree SHA1...')
            result = subprocess.run(
                [git_exec, '-C', tmpdir, 'log', '--all', '--pretty=format:"%T %H"'],
                capture_output=True, text=True, check=True
            )
            output = result.stdout.strip().replace('"', '')
            for line in output.splitlines():
                if line.startswith(git_tree_sha1 + ' '):
                    commit = line.split()[1]
                    break
            else:
                print(f"WARNING: Could not find commit for git tree SHA1 {git_tree_sha1} in repo {repo}")
                print(f"Git log output:\n{output}")
        except subprocess.CalledProcessError as e:
            print(f"Error running git command: {e}")

    return commit


def get_url_from_general(pkg, git_tree_sha1, max_retries=3):
    """Get the package info from the General registry"""
    if not HAS_REQUESTS:
        print("WARNING: requests library not available, cannot fetch package data from General registry")
        return None, None
    if pkg.endswith('_jll'):
        base_url = "https://github.com/JuliaRegistries/General/raw/refs/heads/master/jll/{}/{}/"
    else:
        base_url = "https://github.com/JuliaRegistries/General/raw/refs/heads/master/{}/{}/"
    base_url = base_url.format(pkg[0].upper(), pkg)
    package_url = base_url + "Package.toml"

    sleep_time = 1

    last_exception = None
    while max_retries > 0:
        time.sleep(sleep_time)
        sleep_time *= 2  # exponential backoff
        try:
            package_data = requests.get(package_url).text
        except requests.RequestException as exc:
            last_exception = exc
            print(f"Error fetching package data from General registry: {exc}")
            max_retries -= 1
            continue
        else:
            try:
                package_info = toml.loads(package_data)
                break
            except toml.TomlDecodeError as exc:
                last_exception = exc
                print(f"Error parsing Package.toml for package {pkg} from General registry: {exc}")
                max_retries -= 1
    else:
        print(f"Failed to fetch and parse package data for {pkg} from General registry after multiple attempts")
        print(f"Last error fetching package data from General registry: {last_exception}")
        print(f"Last package data that caused the error:\n{package_data}")
        raise RuntimeError(
            f"Failed to fetch and parse package data for {pkg} from General registry after multiple attempts"
        )

    repo = package_info['repo']
    url = repo.rstrip('/')
    if url.endswith('.git'):
        url = url[:-4]

    if 'github.com' in url:
        url = url + "/archive/"
        filename = f'{git_tree_sha1}.tar.gz'

    if 'gitlab.com' in url:
        # https://gitlab.com/ExpandingMan/ShowCases.jl/-/archive/1ea211f349b40165a2b5fbbc80f771d6dcb725ad/ShowCases.jl-1ea211f349b40165a2b5fbbc80f771d6dcb725ad.tar.gz
        commit = get_commit_from_git_tree_sha1(repo, git_tree_sha1)
        if commit:
            url = url + f"/-/archive/{commit}/"
            filename = f'{pkg}.jl-{commit[:8]}.tar.gz'
        else:
            url = None
            filename = None
            print(f"WARNING: Could not determine commit for git tree SHA1 {git_tree_sha1} in GITLAB repo {repo}")

    return url, filename


def generate_package_data(sourcedir):
    """Extract package data from Manifest.toml, including determining source URLs for
    packages based on available information"""
    manifest_toml = toml.load(os.path.join(sourcedir, 'Manifest.toml'))

    julia_exec = get_julia_exec()

    packages_data = {}

    deps = manifest_toml.get('deps', {})
    for pkg_name, pkg_data in deps.items():
        if len(pkg_data) != 1:
            raise ValueError(
                f"Expected exactly one entry for package {pkg_name} in Manifest.toml deps, "
                f"got {len(pkg_data)}: {pkg_data}"
            )
        pkg_data = pkg_data[0]
        version = pkg_data.get('version')
        git_tree_sha1 = pkg_data.get('git-tree-sha1', None)

        url = None
        item = {
            'name': pkg_name,
            'version': version,
            'checksum': None,
        }

        if url is None and 'repo-url' in pkg_data:
            url = pkg_data['repo-url']
            print(f"Found package {pkg_name:>30s} with explicit repo URL: {url}")

        if url is None and git_tree_sha1 is not None:
            url, download_filename = get_url_from_general(pkg_name, git_tree_sha1)
            filename = f'{pkg_name}-{version}.tar.gz'
            item['sources'] = [{
                'download_filename': download_filename,
                'filename': filename,
            }]
            print(f"Found package {pkg_name:>30s} with git tree SHA1, determined URL from General registry: {url}")

        # Check if the package is part of the Julia standard library, if so we don't need a source URL
        if url is None and julia_exec:
            req = subprocess.run(
                [julia_exec, '-e', f'import Base; println(Base.find_package("{pkg_name}"))'],
                capture_output=True, text=True
            )
            path = req.stdout.strip()
            if path and path != "nothing":
                print(f"Found Package {pkg_name:>30s} is part of the Julia standard library, no source URL needed")
                url = IsJuliaPackage()

        if url is None:
            print(f"WARNING: Could not determine source URL for package {pkg_name} (version {version})")

        item['url'] = url
        packages_data[pkg_name] = item

    return packages_data


def get_package_dep_graph(sourcedir):
    """Helper for generating package dependency graph from Manifest.toml

    Parameters:
        - sourcedir: path to folder containing Manifest.toml

    Returns:
        - nodes: set of package names
        - graph: dict mapping package name to set of packages that depend on it
    """
    manifest_toml = toml.load(os.path.join(sourcedir, 'Manifest.toml'))

    nodes = set()
    graph = defaultdict(set)

    deps = manifest_toml.get('deps', {})
    for pkg_name, pkg_data in deps.items():
        if len(pkg_data) != 1:
            raise ValueError(
                f"Expected exactly one entry for package {pkg_name} in Manifest.toml deps, "
                f"got {len(pkg_data)}: {pkg_data}"
            )
        pkg_data = pkg_data[0]
        nodes.add(pkg_name)
        sub_deps = set(pkg_data.get('deps', []))
        nodes |= sub_deps
        for sub_dep in sub_deps:
            graph[sub_dep].add(pkg_name)

    return nodes, graph


def topological_sort(nodes, graph):
    """Sort packages deps in topological order to ensure dependencies are installed before dependents

    Parameters:
        - nodes: set of package names
        - graph: dict mapping package name to set of packages that depend on it

    Returns:
        - sorted_list: list of package names sorted in topological order
    """
    incoming_count = dict.fromkeys(nodes, 0)
    for parents in graph.values():
        for parent in parents:
            incoming_count[parent] += 1

    sorted_list = []
    while nodes:
        no_incoming = [node for node in nodes if incoming_count[node] == 0]
        if not no_incoming:
            raise ValueError("Graph has a cycle, cannot perform topological sort")
        no_incoming.sort()  # sort alphabetically
        sorted_list.extend(no_incoming)
        for node in no_incoming:
            nodes.remove(node)
            for parent in graph[node]:
                incoming_count[parent] -= 1

    return sorted_list


def generate_exts_list(sourcedir, tab_depth=4):
    """Helper for generating exts_list with Julia packages in topological order"""
    nodes, graph = get_package_dep_graph(sourcedir)
    sorted_packages = topological_sort(nodes, graph)
    package_data = generate_package_data(sourcedir)

    tab = ' ' * tab_depth

    exts_list = []

    exts_list.append('exts_list = [')
    for pkg_name in sorted_packages:
        pkg_info = package_data[pkg_name]
        name = pkg_info['name']
        version = pkg_info['version']
        url = pkg_info['url']
        sources = pkg_info.get('sources', None)
        checksum = pkg_info['checksum']
        if checksum is not None:
            checksum = f"'{checksum}'"
        if isinstance(url, IsJuliaPackage):
            continue
        exts_list.append(tab + f"('{name}', '{version}', {{")
        exts_list.append(tab*2 + f"'easyblock': 'JuliaPackage',")
        exts_list.append(tab*2 + f"'source_urls': ['{url}'],")
        if sources is not None:
            exts_list.append(tab*2 + f"'sources': {sources},")
        exts_list.append(tab*2 + f"'checksums': [{checksum}],")
        exts_list.append(tab + '}),')
    exts_list.append(']')

    return '\n'.join(exts_list)


def main():
    if len(sys.argv) < 2:
        print('Expected path to folder containing Manifest.toml')
        sys.exit(1)
    if len(sys.argv) > 2:
        tab_depth = int(sys.argv[2])
    else:
        tab_depth = 4
    if len(sys.argv) > 3:
        print('Ignoring extra arguments: %s' % sys.argv[3:])

    check_needed_tools()
    print(generate_exts_list(sys.argv[1], tab_depth=tab_depth))


if __name__ == '__main__':
    main()
