![El Chapo](https://uploads-ssl.webflow.com/5e0b0187743608fe07eecd0a/5f13d06c791ec9206e4d0ef7_el%20chapo%20(3).png)

## Setup

Create virtual environment
```sh
virtualenv venv
```
Activate virtual environment
```sh
source venv/bin/activate
```
Install dependencies
```sh
pip install -r requirements.txt
```


## Deployment

Create an AWS account if you dont have one already and retrieve - public key and private key and then configure aws account on your terminal
```sh
aws configure
```

Refer to zappa_settings.json and change the parameters accoring to your application. You are now ready to deploy the application to staging and production.
```sh
zappa deploy <staging/production>
```
You can now configure your short url domain to route all requests to the URL that is given by zappa in the above step. If you have to update the application, run
```sh
zappa update <staging/production>
```
To delete the deployment run
```sh
zappa undeploy <staging/production>
```

## Usage

Create a new shortened URL. The webhook paramater here is optional.
```sh
curl -XPOST '<short_url_domain>/c' -d '{
	"path": "shortpath",
	"webhook": "https://f81421ad32aa6b3f557cec14301e1296.m.pipedream.net?id=idtotrack",
	"redirect_url": "https://google.com"
}' -H "content-type: application/json"
```
Retrieve the original URL from the short url
```sh
curl '<short_url_domain>/shortpath'
```

## Closing note
For more information regarding zappa and all the frameworks that it supports, please check out [zappa](https://github.com/Miserlou/Zappa)
