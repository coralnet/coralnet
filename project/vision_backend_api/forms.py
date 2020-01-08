from __future__ import unicode_literals

from api_core.forms import (
    validate_array, validate_hash, validate_json, validate_integer,
    validate_required_param, validate_string)


def validate_deploy(post_data):
    """
    Expected input data: 'images' member as JSON.
    Returns a new dict with 'images' loaded from JSON, and with integers
    normalized (3 and "3" both become 3).
    """
    images_json = validate_required_param(post_data, 'images')
    images_list = validate_json(images_json, 'images')

    validate_array(images_list, ['images'], check_non_empty=True)

    for image_index, image_spec in enumerate(images_list):

        img_json_path = ['images', image_index]

        validate_hash(
            image_spec, img_json_path, expected_keys=['url', 'points'])

        validate_string(image_spec['url'], img_json_path + ['url'])
        validate_array(
            image_spec['points'], img_json_path + ['points'],
            check_non_empty=True)

        for point_index, point in enumerate(image_spec['points']):

            pt_json_path = img_json_path + ['points', point_index]

            validate_hash(point, pt_json_path, expected_keys=['row', 'column'])

            point['row'] = validate_integer(
                point['row'], pt_json_path + ['row'], min_value=0)
            point['column'] = validate_integer(
                point['column'], pt_json_path + ['column'], min_value=0)

    return dict(images=images_list)
