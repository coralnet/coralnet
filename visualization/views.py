from django.core.paginator import Paginator, EmptyPage, InvalidPage
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render_to_response
from django.template.context import RequestContext
from guardian.decorators import permission_required
from annotations.models import Annotation, Label
from images.models import Source, Value1, Value2, Value3, Value4, Value5, Image
from visualization.forms import VisualizationSearchForm
import Image as imageobj

@permission_required('source_admin', (Source, 'id', 'source_id'))
def visualize_source(request, source_id):
    """
    View for browsing through a source's images.
    """
    kwargs = {
        #this will contain the parameters to filter the images by
        #that way the filter args can be dynamically generated if
        #all possible values are not filled
    }

    pargs = {
        #same as above but needs different indexes because it's used
        #for patch mode. TODO: reimplement this in a non-hackish way
    }

    errors = [] #keeps tracks of errors that occur
    all_images = [] #holds all the images to display
    source = get_object_or_404(Source, id=source_id)
    kwargs['source'] = source

    if request.GET:

        #form to select descriptors to sort images
        form = VisualizationSearchForm(source_id, request.GET)
        if form.is_valid():
            value1Index = request.GET.get('value1', 0)
            value2Index = request.GET.get('value2', 0)
            value3Index = request.GET.get('value3', 0)
            value4Index = request.GET.get('value4', 0)
            value5Index = request.GET.get('value5', 0)
            year = request.GET.get('year', 0)
            label = request.GET.get('label', 0)

            value1List = Value1.objects.filter(source=source)
            value2List = Value2.objects.filter(source=source)
            value3List = Value3.objects.filter(source=source)
            value4List = Value4.objects.filter(source=source)
            value5List = Value5.objects.filter(source=source)

            if value1Index:
                kwargs['value1'] = value1List[int(value1Index)-1]
                pargs['image__metadata__value1'] = value1List[int(value1Index)-1]
            if value2Index:
                kwargs['value2'] = value2List[int(value2Index)-1]
                pargs['image__metadata__value2'] = value2List[int(value2Index)-1]
            if value3Index:
                kwargs['value3'] = value3List[int(value3Index)-1]
                pargs['image__metadata__value3'] = value3List[int(value3Index)-1]
            if value4Index:
                kwargs['value4'] = value4List[int(value4Index)-1]
                pargs['image__metadata__value4'] = value4List[int(value4Index)-1]
            if value5Index:
                kwargs['value5'] = value5List[int(value5Index)-1]
                pargs['image__metadata__value5'] = value5List[int(value5Index)-1]
            if year:
                kwargs['metadata__photo_date__year'] = year

            if label:
                all_images = Image.objects.filter(**kwargs).order_by('-upload_date')

            else:
                #get all annotations for the source that contain the label
                label = Label.objects.filter(name=label)
                annotations = Annotation.objects.filter(source=source, label=label, **pargs)
                #TODO: add searching annotations based on key/value pairs

                #create a cropped image for each annotation
                for annotation in annotations:
                    path = annotation.image.original_file
                    image = imageobj.open(path)

                    max_x = Annotation.image.original_width
                    max_y = Annotation.image.original_height
                    x = Annotation.point.row
                    y = Annotation.point.column

                    if x-75 > 0:
                        left = x-75
                    else:
                        left = 0

                    if x+75 < max_x:
                        right = x+75
                    else:
                        right = max_x

                    if y-75 > 0:
                        upper = y-75
                    else:
                        upper = 0

                    if y+75 < max_y:
                        lower = y+75
                    else:
                        lower = 0

                    #mark the subrectangle to be select from the image
                    box = (left,upper,right,lower)

                    #get the image
                    region = image.crop(box)
                    all_images.append(region)

    else:
        form = VisualizationSearchForm(source_id)
        all_images = Image.objects.filter(source=source).order_by('-upload_date')

    if not all_images and not errors:
        if request.GET:
            errors.append("Sorry, no images matched your query")
        else:
            errors.append("Sorry, there are no images for this source yet. Please upload some.")

    paginator = Paginator(all_images, 20) # Show 25 images per page

    # Make sure page request is an int. If not, deliver first page.
    try:
        page = int(request.GET.get('page', '1'))
    except ValueError:
        page = 1

    # If page request (9999) is out of range, deliver last page of results.
    try:
        images = paginator.page(page)
    except (EmptyPage, InvalidPage):
        images = paginator.page(paginator.num_pages)

    return render_to_response('visualization/visualize_source.html', {
        'errors': errors,
        'form': form,
        'source': source,
        'images': images,
        },
        context_instance=RequestContext(request)
        
    )
