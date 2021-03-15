

# S3 API

import boto3
from botocore.exceptions import ClientError



import os.path
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.http import HttpResponse, HttpResponseRedirect, Http404, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django import forms
from django.views.decorators.csrf import csrf_exempt
import json
import ast
import csv
import codecs
import random
import string
from django.contrib.auth import user_logged_in
from django.dispatch.dispatcher import receiver
from django.contrib.sessions.models import Session
from django.utils import timezone
import datetime
import pytz

from .models import User, Team, Ordering, GlobalVariables, Question, Answer, AnswerFiles

from PIL import Image
import io

import base64
from threading import *

from django.contrib import messages

#Function for uploading file onto S3

def upload_file(file_name, object_name=None):
    """Upload a file to an S3 bucket

    :param file_name: File to upload
    :param bucket: Bucket to upload to
    :param object_name: S3 object name. If not specified then file_name is used
    :return: True if file was uploaded, else False
    """

    # If S3 object_name was not specified, use file_name
    if object_name is None:
        object_name = file_name

        # Upload the file
        s3_client = boto3.client('s3')
        try:
            response = s3_client.upload_file(file_name, "mimamsauploadedanswers", object_name)
        except ClientError as e:
            print("oh no")
            return False
        return True



#  User account related views




def login_view(request):
    if request.method == "POST":

        # Attempt to sign user in
        email = (request.POST["email"]).lower()
        password = request.POST["password"]
        print(password)
        if User.objects.filter(username=email).exists():
            user=User.objects.get(username=email)
            if user.check_password(password):
                if user.session_key: # check if user has session_key. This will be true for users logged in on another device
                    try:
                        s = Session.objects.get(session_key=user.session_key)
                        s.delete()
                    except Session.DoesNotExist:
                        pass
                login(request, user)
                user.session_key = request.session.session_key
                user.save()
                return HttpResponseRedirect(reverse("dashboard"))
        return render(request, "examPortalApp/index.html", {
            "message": "Invalid username and/or password."
        })
    else:
        if request.user.is_authenticated:
            return HttpResponseRedirect(reverse('dashboard'))
        return render(request, "examPortalApp/index.html")

# This view does two things at once
# (1) It adds new user and team accounts into our database and creates folders in the drive where each team would upload their answers
# (2) The POST method returns a JSON object of all the newest accounts along with the newly generated passwords so that the passwords could be sent to their respective email accounts
# TODO: Make this view a background task

def update_accounts(request):
    class GeneratePass(Thread):
        def run(self):
            file=request.FILES['file']
            if file:
                reader = csv.DictReader(codecs.iterdecode(file, 'utf-8'))
                generated_passwords={}
                print("It begins")
                for row in reader:
                    team_id = row["TEAM ID"]
                    print(row["SEQUENCE"])
                    try:
                        team=Team.objects.create(team_id=team_id, sequence=row["SEQUENCE"], college=row["COLLEGE"], zone=row["ZONE CODE"])
                        team.save()
                        print(team_id+" saved")
                    except IntegrityError:
                        team=Team.objects.get(team_id=team_id)
                        print(team_id)
                    for i in range(4):
                        if row["EMAIL ID "+str(i+1)]=="":
                            continue
                        try:
                            password=''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(8))
                            user=User.objects.create_user(username=(row["EMAIL ID "+str(i+1)]).lower(), email=(row["EMAIL ID "+str(i+1)]).lower(), password=password, generated_pass=password)
                            if i==0:
                                user.phone_number=row["PHONE 1"]
                                user.save()
                        except IntegrityError:
                            print(row["EMAIL ID "+str(i+1)])
                            user=User.objects.get(email=(row["EMAIL ID "+str(i+1)]).lower())
                        if user.passwordSet==False:
                            generated_passwords[(row["EMAIL ID "+str(i+1)]).lower()]=user.generated_pass
                        if team.users.all().filter(email=user.email).count()==0:
                            team.users.add(user)
                            ordering=Ordering.objects.create(team_instance=team, user_instance=user, order_index=i+1)
                            ordering.save()
                            team.save()
                return JsonResponse(generated_passwords)
            print("Accounts updated")
    if request.user.username=="admin":
        if request.method=="POST":
            #Authenticate user trying to update the accounts and generate passwords
            thread1 = GeneratePass()
            thread1.start()
            return render(request,"examPortalApp/updateconfirmation.html",{'confirmvar':'Updates initiated'})
        else:
            return render(request,"examPortalApp/update.html")
    else:
        return HttpResponseRedirect(reverse("dashboard"))

def unset_passwords(request):
    password_list={}
    for user in User.objects.all():
        if not user.passwordSet and user.username!="admin":
            password_list[user.email]=user.generated_pass
    return JsonResponse(password_list)

@login_required
def change_password(request):
    if request.method == 'POST':
        user = request.user
        email = (request.POST["email"]).lower()
        old_password = request.POST["old_password"]
        new_password = request.POST["new_password"]
        confirm_password = request.POST["confirm_password"]
        if new_password==confirm_password and new_password!="":
            if user.username==email and user.check_password(old_password):
                user.set_password(new_password)
                user.passwordSet=True
                user.save()
            elif user.username=="admin" and user.check_password(old_password): #backdoor for admin to change the password of someone else. admin has to enter his/her own password in place of old password
                try:
                    reset_user=User.objects.get(username=email)
                except:
                    return render(request, "examPortalApp/change_password.html", {
                        "message": "Email not registered"
                    })
                reset_user.set_password(new_password)
                user.passwordSet=True
                user.save()
            else:
                return render(request, "examPortalApp/change_password.html", {
                    "message": "Your credentials don't match."
                })
        else:
            if new_password!=confirm_password:
                return render(request, "examPortalApp/change_password.html", {
                "message": "Passwords don't match."
                })
            else:
                return render(request,"examPortalApp/change_password.html", {
                "message": "Password cannot be blank."
                })
        logout(request)
        return render(request, "examPortalApp/index.html", {
            "message": "Password successfully updated."
        })
    else:
        return render(request, "examPortalApp/change_password.html")

def logout_view(request):
    logout(request)
    return HttpResponseRedirect(reverse("index"))




# Dashboard




def dashboard(request):
    if request.user.is_authenticated:
        if request.user.passwordSet or request.user.username=="admin":
            return render(request, "examPortalApp/dashboard.html")
        else:
            return HttpResponseRedirect(reverse("change_password"))
    #If not logged in, redirect to login page
    else:
        return HttpResponseRedirect(reverse("index"))




# Views related to the exam portal itself



@login_required
def open_test(request, qnumber=None, message=""):
    now = timezone.now()
    test_start=(GlobalVariables.objects.get_or_create(pk=1, defaults={'test_start': pytz.UTC.localize(datetime.datetime(2021, 1, 26, 22, 0, 0)),  'test_end': pytz.UTC.localize(datetime.datetime(2021, 1, 26, 22, 30, 0))})[0]).test_start
    test_end=GlobalVariables.objects.get(pk=1).test_end
    q_count= Question.objects.all().count();
    q_current = 1 if (qnumber is None) else int(qnumber);
    q=Question.objects.get(question_number=qnumber)
    team=request.user.team_set.first()

    #If test hasn't started yet, show the waiting page,
    #If it has started but hasn't ended, show the testportal
    #If it's ended show the "Test ended" page

    if now<test_start:
        return render(request, "examPortalApp/waitingroom.html", {"UTCDate": test_start.day, "UTCMonth": test_start.month, "UTCYear": test_start.year, "UTCHours": test_start.hour, "UTCMinutes": test_start.minute, "UTCSeconds": test_start.second})
    if now<test_end:
        review_questions=list(Question.objects.filter(answer__team_instance=team, answer__status='r').values_list('question_number', flat=True))
        answered_questions=list(Question.objects.filter(answer__team_instance=team, answer__status='a').values_list('question_number', flat=True))
        if q.question_type=='s':
            a=(Answer.objects.get_or_create(question_instance=q, team_instance=request.user.team_set.first()))[0]
            uploaded_files=list(AnswerFiles.objects.filter(answer_instance = a).order_by('page_no').values_list('answer_filename', flat=True))
            return render(request, "examPortalApp/testportal.html", {"uploaded_files":uploaded_files, "answer_text": a.answer_content, "selected_options": [], "review_questions": review_questions, "answered_questions": answered_questions, "answer_status": a.status, "team": team, "labels": [], "options": [], "QNum": q_current, "QCount": q_count, "QType": 's', "content": q.question_content, "UTCDate": test_end.day, "UTCMonth": test_end.month, "UTCYear": test_end.year, "UTCHours": test_end.hour, "UTCMinutes": test_end.minute, "UTCSeconds": test_end.second})
        if q.question_type=='m':
            a=(Answer.objects.get_or_create(question_instance=q, team_instance=request.user.team_set.first()))[0]
            if a.answer_content=="":
                a.answer_content=str([])
                a.save()
            selected_options=ast.literal_eval(a.answer_content)
            content=ast.literal_eval(q.question_content)
            setup=content[0]
            option_sets=[]
            labels=[]
            i=1
            while i<len(content):
                option_sets+=[[content[i][0]]+content[i][1]]
                i+=1
            return render(request, "examPortalApp/testportal.html", {"answer_text": "", "selected_options": selected_options, "review_questions": review_questions, "answered_questions": answered_questions, "answer_status": a.status, "team": team, "labels": labels, "options": option_sets, "QNum": q_current, "QCount": q_count, "QType": 'm', "content": setup, "UTCDate": test_end.day, "UTCMonth": test_end.month, "UTCYear": test_end.year, "UTCHours": test_end.hour, "UTCMinutes": test_end.minute, "UTCSeconds": test_end.second})
        if q.question_type=='t':
            a=(Answer.objects.get_or_create(question_instance=q, team_instance=request.user.team_set.first()))[0]
            uploaded_files=list(AnswerFiles.objects.filter(answer_instance = a).order_by('page_no').values_list('answer_filename', flat=True))
            if a.answer_content=="":
                a.answer_content=str([[], ""])
                a.save()
            selected_option=(ast.literal_eval(a.answer_content))[0]
            content=ast.literal_eval(q.question_content)
            setup=content[0]
            options=content[1]
            return render(request, "examPortalApp/testportal.html", {"uploaded_files":uploaded_files, "answer_text": (ast.literal_eval(a.answer_content))[1], "selected_options": selected_option, "review_questions": review_questions, "answered_questions": answered_questions, "answer_status": a.status, "team": team, "labels": [], "options": options, "QNum": q_current, "QCount": q_count, "QType": 't', "content": setup, "UTCDate": test_end.day, "UTCMonth": test_end.month, "UTCYear": test_end.year, "UTCHours": test_end.hour, "UTCMinutes": test_end.minute, "UTCSeconds": test_end.second})

    return render(request, "examPortalApp/testended.html")


@login_required
def get_answers(request, page_no, qnumber):

    team=request.user.team_set.first()

    q=Question.objects.get(question_number=int(qnumber))
    subject=q.question_subject

    s3 = boto3.client("s3")
    response = s3.list_objects_v2(
            Bucket='mimamsauploadedanswers',
            Prefix =subject+'/Q'+str(q.question_number)+'/'+team.team_id,
            MaxKeys=100 )
    print(response)
    images=[]
    if "Contents" in response:
        for i in range(len(response["Contents"])):
            fh = io.BytesIO()

            # Initialise a downloader object to download the file
            s3.download_fileobj('mimamsauploadedanswers', subject+'/Q'+str(q.question_number)+'/'+team.team_id+'/'+str(i)+'.jpeg', fh)

            fh.seek(0)

            prefix = 'data:image/jpeg;base64,'
            contents=fh.read()
            data_url = prefix + str((base64.b64encode(contents)).decode('ascii'))
            images+=[data_url]

    #Pass the list of data blob text in a JSON response
    return JsonResponse({"images":images})

@login_required
def get_m_answers(request, qnumber):
    team=request.user.team_set.first()
    q=Question.objects.get(question_number=int(qnumber))
    try:
        a=Answer.objects.get(team_instance=team, question_instance=q)
        return JsonResponse({"answers":ast.literal_eval(a.answer_content)})
    except:
        return JsonResponse({"answers": []})


@login_required
def get_t_answers(request, qnumber):
    team=request.user.team_set.first()
    q=Question.objects.get(question_number=int(qnumber))
    try:
        a=Answer.objects.get(team_instance=team, question_instance=q)
        l=ast.literal_eval(a.answer_content)
        if len(l)==1:
            return JsonResponse({"choice":l[0][0], "text": ""})
        else:
            return JsonResponse({"choice":l[0][0], "text": l[1]})
    except:
        return JsonResponse({"choice":-1, "images": [], "text": ""})


@login_required
def submit_MCQ(request):
    qnumber=request.POST["qnumber"]
    i=1
    answer=[]
    while "choice-"+str(i) in request.POST:
        answer+=[int(request.POST["choice-"+str(i)])]
        i+=1

    q=Question.objects.get(question_number=request.POST["qnumber"])
    a=(Answer.objects.get_or_create(question_instance=q, team_instance=request.user.team_set.first()))[0]
    a.answer_content=str(answer)
    if len(answer)!=0:
        a.status='a'
    elif a.status=='a':
        a.status='u'
    a.save()
    return HttpResponseRedirect(reverse("test_no", kwargs={"qnumber":str(qnumber)}))

#This function is for saving the choice, not the explanation. The latter is handled by upload_answer/upload_text_answer
@login_required
def submit_TT(request):
    i=1
    answer=[[], ""]
    if "choice" in request.POST:
        answer[0]=[int(request.POST["choice"])]
    q=Question.objects.get(question_number=request.POST["qnumber"])
    qnumber=request.POST["qnumber"]

    a=Answer.objects.get_or_create(question_instance=q, team_instance=request.user.team_set.first())[0]
    if a.answer_content!="":
        answer[1]=(ast.literal_eval(a.answer_content))[1]
    a.answer_content=str(answer)
    a.save()
    return HttpResponseRedirect(reverse("test_no", kwargs={"qnumber":str(qnumber)}))

@login_required
def upload_text_answer(request):
    q=Question.objects.get(question_number=request.POST["qnumber"])
    qnumber=request.POST["qnumber"]
    subject=q.question_subject
    a=Answer.objects.get_or_create(question_instance=q, team_instance=request.user.team_set.first())[0]
    AnswerFiles.objects.filter(answer_instance = a).delete()
    user=request.user
    team=user.team_set.first()

    s3 = boto3.client('s3')

    response = s3.list_objects_v2(
        Bucket='mimamsauploadedanswers',
        Prefix =subject+'/Q'+str(qnumber)+'/'+team.team_id,
        MaxKeys=100)

    if "Contents" in response:
        for i in range(len(response["Contents"])):
            s3.delete_object(Bucket="mimamsauploadedanswers", Key=(subject+'/Q'+qnumber+'/'+team.team_id+'/'+str(i)+'.jpeg'))


    if q.question_type=='s':
        a.answer_content=request.POST["answer_text"]
    elif q.question_type=='t':
        a.answer_content=[(ast.literal_eval(a.answer_content))[0], request.POST["answer_text"]]
    a.save()
    return HttpResponseRedirect(reverse("test_no", kwargs={"qnumber":str(qnumber)}))


@login_required
def upload_answer(request):
    user=request.user
    team=user.team_set.first()
    print(request.POST)
    answerfile=request.FILES["file"]
    qnumber=request.POST["qnumber"]
    try:
        q=Question.objects.get(question_number=int(qnumber))
        a=Answer.objects.get_or_create(question_instance=q, team_instance=request.user.team_set.first())[0]
    except:
        print(qnumber)
        raise Http404;
    subject=q.question_subject

    if q.question_type=='s':
        a.answer_content=""
    elif q.question_type=='t':
        a.answer_content=[(ast.literal_eval(a.answer_content))[0], ""]
    a.save()

    if team is None:
        return HttpResponseRedirect(reverse("test_no", kwargs={"qnumber":str(qnumber)}))
    #Resize and compress uploaded image

    try:
        im = Image.open(answerfile)
        im.verify() #I perform also verify, don't know if he sees other types o defects
        # im1.close() #reload is necessary in my case
    except:
        #manage exceptions here
        messages.info(request, 'Image file corrupt or unsupported')
        return HttpResponseRedirect(reverse("test_no", kwargs={"qnumber":str(qnumber)}))
    # im.seek(0)
    im = Image.open(answerfile)
    w, h = im.size
    f=(250000/(w*h))**(0.5)

    im=im.resize((int(w*f), int(h*f)))
    rgb_im = im.convert("RGB")

    b = io.BytesIO()
    rgb_im.save(b, "JPEG", optimize=True, quality=70)
    b.seek(0)

    s3 = boto3.client('s3')

    """response = s3.list_objects_v2(
        Bucket='mimamsauploadedanswers',
        Prefix =subject+'/Q'+str(qnumber)+'/'+team.team_id,
        MaxKeys=100)"""

    ansinst = Answer.objects.get_or_create(team_instance = team, question_instance = q)
    ansinst[0].save()
    noofpages = AnswerFiles.objects.filter(answer_instance = (ansinst[0])).count()
    print("oyeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee")
    print(noofpages)

    file_name = os.path.basename(answerfile.name)

    s3.upload_fileobj(b, "mimamsauploadedanswers", subject+'/Q'+qnumber+'/'+team.team_id+'/'+str(noofpages)+'.jpeg')
    af = AnswerFiles.objects.create(answer_instance=ansinst[0], answer_filename=file_name, page_no = noofpages)
    af.save()

    return HttpResponseRedirect(reverse("test_no", kwargs={"qnumber":str(qnumber)}))


# TODO:
@login_required
def end_test(request):
    pass


@login_required
def mark_for_review(request, qnumber):
    user=request.user
    team=user.team_set.first()
    q=Question.objects.get(question_number=int(qnumber))
    a=Answer.objects.get_or_create(question_instance=q, team_instance=request.user.team_set.first())[0]
    a.status='r'
    a.save()
    return HttpResponseRedirect(reverse("test_no", kwargs={"qnumber":str(qnumber)}))

@login_required
def mark_as_answered(request, qnumber):
    user=request.user
    team=user.team_set.first()
    q=Question.objects.get(question_number=int(qnumber))
    a=Answer.objects.get_or_create(question_instance=q, team_instance=request.user.team_set.first())[0]
    a.status='a'
    a.save()
    return HttpResponseRedirect(reverse("test_no", kwargs={"qnumber":str(qnumber)}))

@login_required
def mark_as_unanswered(request, qnumber):
    user=request.user
    team=user.team_set.first()
    q=Question.objects.get(question_number=int(qnumber))
    a=Answer.objects.get_or_create(question_instance=q, team_instance=request.user.team_set.first())[0]
    if a.question_instance.question_type=='m':
        if a.answer_content=="[]":
            a.status='u'
        else:
            a.status='a'
    else:
        a.status='u'
    a.save()
    return HttpResponseRedirect(reverse("test_no", kwargs={"qnumber":str(qnumber)}))


@login_required
def clear_t_options(request, qnumber):
    user=request.user
    team=user.team_set.first()
    q=Question.objects.get(question_number=int(qnumber))
    a=Answer.objects.get_or_create(question_instance=q, team_instance=request.user.team_set.first())[0]
    a.answer_content=str([[], (ast.literal_eval(a.answer_content))[1]])
    if a.status=='a':
        a.status='u';
    a.save()
    return HttpResponseRedirect(reverse("test_no", kwargs={"qnumber":str(qnumber)}))




# Question making portal




@login_required
def question_making_page(request, page=1):
    if request.user.username=="admin":
        q=Paginator(Question.objects.all().order_by("question_number"), 10)
        if page not in q.page_range:
            raise Http404
        return render(request, "examPortalApp/questionportal.html", {"questions": q.page(page), "page": page, "pagecount": q.num_pages})
    #If not logged in as admin, redirect to dashboard
    else:
        return HttpResponseRedirect(reverse("dashboard"))


@login_required
def post_question(request):
    if request.user.username=="admin":
        if request.POST["qtype"]=='s':
            q=Question(question_content=(request.POST["content"]).replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>"), question_number=(Question.objects.all().count()+1), question_subject=request.POST["subject"], question_type='s', question_answers='')
            q.save()
            #Redirect to page 1 of the question making portal
            return HttpResponseRedirect(reverse("questionportal", kwargs={'page':1}))
        if request.POST["qtype"]=='m':
            answers=[]
            content=[(request.POST["content"]).replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>")]
            i=1
            while "opt-"+str(i) in request.POST:
                if (i-1)%4==0:
                    content+=[[request.POST["mcq-set-"+str(int((i-1)/4))+"-label"], []]]
                content[1+int((i-1)/4)][1]+=[request.POST["opt-"+str(i)]]
                if "correct_"+str(i) in request.POST:
                    answers+=[i]
                i+=1
            q=Question(question_content=str(content), question_number=(Question.objects.all().count()+1), question_subject=request.POST["subject"], question_type='m', question_answers=str(answers))
            q.save()
            return HttpResponseRedirect(reverse("questionportal", kwargs={'page':1}))
        if request.POST["qtype"]=='t':
            answers=[]
            content=[(request.POST["content"]).replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>"), []]
            i=1
            while "opt-"+str(i) in request.POST:
                content[1]+=[request.POST["opt-"+str(i)]]
                if "correct_"+str(i) in request.POST:
                    answers+=[i]
                i+=1
            q=Question(question_content=str(content), question_number=(Question.objects.all().count()+1), question_subject=request.POST["subject"], question_type='t', question_answers=str(answers))
            q.save()
            return HttpResponseRedirect(reverse("questionportal", kwargs={'page':1}))

    else:
        return HttpResponseRedirect(reverse("dashboard"))



# TODO:
@login_required
def delete_question(request):
    if request.user.username=="admin":
        print(request.body)
        post_data = json.loads(request.body.decode("utf-8"))
        q=Question.objects.get(id=post_data["id"])
        print(q.question_content)
        total=Question.objects.all().count()
        qnum=q.question_number
        q.delete()
        for i in range(total-qnum):
            m=Question.objects.get(question_number=qnum+(i+1))
            m.question_number-=1
            m.save()
        print("--------------")
        print(('{"content":"')+(q.question_content)+('", "subject":"'+q.question_subject+'"}'))
        return HttpResponse(status=201)

@login_required
def edit_question(request):
    subjects=["Physics", "Biology", "Math", "Chemistry"]
    if request.user.username=="admin":
        print(request.POST)
        q=Question.objects.get(id=int(request.POST["id"]))
        print(q.question_content)
        q.question_content=(request.POST["content"]).replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>")
        if request.POST["subject"] in subjects:
            q.question_subject=request.POST["subject"]
        qnumber=int(request.POST["qnumber"])
        total=Question.objects.all().count()
        if qnumber<1:
            qnumber=1
        elif qnumber>total:
            qnumber=total
        old_qnum=q.question_number
        if qnumber>old_qnum:
            q.question_number=total+1
            q.save()
            for i in range(qnumber-old_qnum):
                m=Question.objects.get(question_number=old_qnum+(i+1))
                m.question_number-=1
                m.save()
            q.question_number=qnumber
        elif qnumber<old_qnum:
            q.question_number=total+1
            q.save()
            for i in range(old_qnum-qnumber):
                m=Question.objects.get(question_number=old_qnum-(i+1))
                m.question_number+=1
                m.save()
            q.question_number=qnumber
        q.save()
        print("--------------")
        print(('{"content":"')+(q.question_content)+('", "subject":"'+q.question_subject+'"}'))
        return HttpResponseRedirect(reverse("questionportal", kwargs={'page':1}))

# TODO:
@login_required
def move_to(request):
    pass

# TODO:
@login_required
def media_view(request):
    pass

# TODO:
@login_required
def upload_media(request):
    pass

# TODO:
@login_required
def delete_media(request):
    pass
