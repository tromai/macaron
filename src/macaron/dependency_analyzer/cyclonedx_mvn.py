# Copyright (c) 2022 - 2022, Oracle and/or its affiliates. All rights reserved.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/.

"""This module processes the JSON dependency output files generated by CycloneDX Maven plugin.

It also collects the direct dependencies that should be processed by Macaron.
See https://github.com/CycloneDX/cyclonedx-maven-plugin.
"""

import glob
import json
import logging
import os

from macaron.dependency_analyzer.dependency_resolver import DependencyAnalyzer, DependencyInfo
from macaron.output_reporter.results import SCMStatus

logger: logging.Logger = logging.getLogger(__name__)


class CycloneDxMaven(DependencyAnalyzer):
    """This class implements the CycloneDX Maven plugin analyzer."""

    def get_cmd(self) -> list:
        """Return the CLI command to run the CycloneDX Maven plugin.

        Returns
        -------
        list
            The command line arguments.
        """
        logger.info(
            (
                "The SBOM generator has started resolving the dependencies and storing them in %s files. "
                "This might take a while..."
            ),
            self.file_name,
        )
        return [
            os.path.join(self.resources_path, "mvnw"),
            f"org.cyclonedx:cyclonedx-maven-plugin:{self.tool_version}:makeAggregateBom",
            "-D",
            "includeTestScope=true",
        ]

    def collect_dependencies(self, dir_path: str) -> dict:
        """Process the dependency JSON files and collect direct dependencies.

        Parameters
        ----------
        dir_path : str
            Path to the repo.

        Returns
        -------
        dict
            A dictionary where artifacts are grouped based on "artifactId:groupId".
        """
        # Load the top level file separately as it has different content.
        top_path = os.path.join(dir_path, "target", self.file_name)

        try:
            with open(top_path, encoding="utf8") as file:
                components = json.load(file).get("components")
        except FileNotFoundError:
            logger.error("Could not find dependency analysis %s file.", self.file_name)
        except ValueError:
            logger.error("Could not process the top level dependencies at %s", top_path)

        # Collect all the dependency files recursively.
        file_paths = glob.glob(os.path.join(dir_path, "**", "target", self.file_name), recursive=True)

        direct_deps = []
        for file_path in file_paths:
            with open(file_path, encoding="utf8") as file:
                try:
                    deps = json.load(file)
                except ValueError:
                    logger.error("Could not process the dependencies at %s", file_path)

            bom_ref = deps.get("metadata").get("component").get("bom-ref")
            self.submodules.add(bom_ref)
            for node in deps.get("dependencies"):
                if node.get("ref") == bom_ref:
                    direct_deps.extend(node.get("dependsOn"))

        for dependency in direct_deps:
            if dependency in self.submodules:
                continue
            key = ""
            for component in components:
                if dependency == component.get("bom-ref"):
                    key = f"{component.get('group')}:{component.get('name')}"
                    item = DependencyInfo(
                        version=component.get("version"),
                        group=component.get("group"),
                        name=component.get("name"),
                        url="",
                        note="",
                        available=SCMStatus.AVAILABLE,
                    )

                    # Some of the components, such as submodules don't have external references.
                    if component.get("externalReferences") is None:
                        logger.debug(
                            "Could not find external references for %s. Skipping...",
                            component.get("bom-ref"),
                        )
                    else:
                        # Find a valid URL.
                        item["url"] = self._find_valid_url(
                            [link.get("url") for link in component.get("externalReferences")]
                        )

                    self._add_latest_version(item, key)
                    break

        if self.debug:
            with open(self.debug_path, "w", encoding="utf8") as debug_file:
                debug_file.write(json.dumps(self.all_versions))

        return self.latest_versions