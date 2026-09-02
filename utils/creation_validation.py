from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, strict=True)]


class _CreationLink(BaseModel):
    id: NonEmptyString
    name: str | None = None
    label: str | None = None

    model_config = ConfigDict(extra='forbid')


class SampleCreationLink(_CreationLink):
    type: Literal['sample_parent', 'sample_child', 'linked_dataset']


class DatasetCreationLink(_CreationLink):
    type: Literal['linked_sample', 'dataset_parent', 'dataset_child']


class _CreationExtras(BaseModel):
    scientific_metadata: dict[str, Any] | None = None

    @field_validator('links', check_fields=False)
    @classmethod
    def deduplicate_links(cls, links):
        unique = []
        seen = set()
        for link in links:
            key = (link.type, link.id)
            if key not in seen:
                seen.add(key)
                unique.append(link)
        return unique


class SampleCreationExtras(_CreationExtras):
    links: list[SampleCreationLink] = Field(default_factory=list)


class DatasetCreationExtras(_CreationExtras):
    links: list[DatasetCreationLink] = Field(default_factory=list)


class ScientificMetadataInput(BaseModel):
    scientific_metadata: dict[str, Any] | None = None


def validate_creation_extras(data, resource_type):
    values = {
        'links': data.get('links', []),
        'scientific_metadata': data.get('scientific_metadata'),
    }
    model = SampleCreationExtras if resource_type == 'sample' else DatasetCreationExtras
    extras = model.model_validate(values)
    return (
        [link.model_dump(exclude_none=True) for link in extras.links],
        extras.scientific_metadata,
    )


def validate_scientific_metadata(value):
    return ScientificMetadataInput.model_validate({
        'scientific_metadata': value,
    }).scientific_metadata
