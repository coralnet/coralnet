# Utility methods used by models.py.
#
# These methods should not import anything from models.py.  Otherwise,
# there will be circular import dependencies.  Utility functions
# that use models.py should go in the general utility functions
# file, utils.py.

from django.db import models


class PointGenerationTypes(models.TextChoices):
    SIMPLE = 'm', "Simple Random"
    STRATIFIED = 't', "Stratified Random"
    UNIFORM = 'u', "Uniform Grid"


class PointCreationTypes(models.TextChoices):
    SIMPLE = PointGenerationTypes.SIMPLE
    STRATIFIED = PointGenerationTypes.STRATIFIED
    UNIFORM = PointGenerationTypes.UNIFORM
    IMPORTED = 'i', "Imported"


class PointGen:
    """
    Utility class for converting between various formats of point creation
    specs: database format, short args format, and source-form args format.

    Examples of the database format:
    m_80 -> Simple random, 80 points
    t_8_6_4 -> Stratified random, 8x6 cells, 4 points per cell
    u_10_8 -> Uniform grid, 10x8 grid
    i_80 -> Imported, 80 points
    """
    Types = PointCreationTypes

    def __init__(
        self,
        type=None,
        points=None,
        cell_rows=None,
        cell_columns=None,
        per_cell=None,
    ):
        # Also accept these values as the `type`.
        # This makes it easier for callers to use this method without
        # needing to import PointGen to get the type constants.
        # (Later, we might want to just change the DB-level type constants
        # to be easier to remember, but this can tide us over for now.)
        alt_type_codes = {
            'simple': PointGen.Types.SIMPLE.value,
            'stratified': PointGen.Types.STRATIFIED.value,
            'uniform': PointGen.Types.UNIFORM.value,
            'imported': PointGen.Types.IMPORTED.value,
        }
        if type in alt_type_codes:
            type = alt_type_codes[type]

        self.type = type
        self.points = None if points is None else int(points)
        self.cell_rows = None if cell_rows is None else int(cell_rows)
        self.cell_columns = None if cell_columns is None else int(cell_columns)
        self.per_cell = None if per_cell is None else int(per_cell)

    @classmethod
    def _number_fields_for_type(cls, type):
        match type:
            case cls.Types.SIMPLE.value:
                return ['points']
            case cls.Types.STRATIFIED.value:
                return ['cell_rows', 'cell_columns', 'per_cell']
            case cls.Types.UNIFORM.value:
                return ['cell_rows', 'cell_columns']
            case cls.Types.IMPORTED.value:
                return ['points']
            case _:
                raise ValueError(f"Unsupported type: {type}")

    @property
    def number_fields(self):
        return self._number_fields_for_type(self.type)

    @property
    def db_value(self):
        return '_'.join(
            [self.type]
            +
            [str(getattr(self, field))
             for field in self.number_fields]
        )

    source_form_field_order = [
        'type', 'points', 'cell_rows', 'cell_columns', 'per_cell',
    ]

    @property
    def source_form_kwargs(self):
        """
        Kwargs that can be submitted to the new source or edit source form.
        """
        field_mapping = {
            field_name: f'default_point_generation_method_{index}'
            for index, field_name in enumerate(self.source_form_field_order)
        }
        return {
            field_mapping[field]: getattr(self, field)
            for field in ['type'] + self.number_fields
        }

    @classmethod
    def from_db_value(cls, db_value):
        tokens = db_value.split('_')
        type = tokens[0]
        number_fields = cls._number_fields_for_type(type)
        return cls(type=type, **dict(zip(number_fields, tokens[1:])))

    def __str__(self):
        """
        Print in readable format.
        """
        match self.type:
            case self.Types.SIMPLE.value:
                return f"Simple random, {self.points} points"
            case self.Types.STRATIFIED.value:
                return (
                    f"Stratified random, {self.cell_rows} rows"
                    f" x {self.cell_columns} columns of cells,"
                    f" {self.per_cell} points per cell"
                    f" (total of {self.total_points} points)"
                )
            case self.Types.UNIFORM.value:
                return (
                    f"Uniform grid,"
                    f" {self.cell_rows} rows x {self.cell_columns} columns"
                    f" (total of {self.total_points} points)"
                )
            case self.Types.IMPORTED.value:
                return f"Imported, {self.points} points"
            case _:
                raise ValueError(f"Unsupported type: {self.type}")

    @property
    def total_points(self):
        match self.type:
            case self.Types.SIMPLE.value:
                return self.points
            case self.Types.STRATIFIED.value:
                return (
                    self.cell_rows * self.cell_columns
                    * self.per_cell
                )
            case self.Types.UNIFORM.value:
                return self.cell_rows * self.cell_columns
            case self.Types.IMPORTED.value:
                return self.points
            case _:
                raise ValueError(f"Unsupported type: {self.type}")
