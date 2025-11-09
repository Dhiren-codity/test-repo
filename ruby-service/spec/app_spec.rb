# frozen_string_literal: true

require 'spec_helper'
require 'time'

RSpec.describe PolyglotAPI do
  include Rack::Test::Methods

  def app
    PolyglotAPI
  end

  describe 'GET /health' do
    it 'returns healthy status' do
      get '/health'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['status']).to eq('healthy')
    end
  end

  describe 'POST /analyze' do
    it 'accepts valid content' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'python', 'lines' => ['def test'] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 85.0, 'issues' => [] })

      post '/analyze', { content: 'def test(): pass', path: 'test.py' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response).to have_key('summary')
    end

    it 'returns 400 when content is missing' do
      post '/analyze', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to match(/Missing content/)
    end

    it 'returns 400 when JSON is invalid and params do not include content' do
      post '/analyze', 'invalid{json', 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to match(/Missing content/)
    end

    it 'detects language from path and passes it to python service (ruby)' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'ruby', 'lines' => ['puts 1'] })

      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(language: 'ruby', content: 'puts 1'))
        .and_return({ 'score' => 70, 'issues' => [] })

      post '/analyze', { content: 'puts 1', path: 'test.rb' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
    end

    it 'uses unknown language when extension is not recognized' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'unknown', 'lines' => ['??'] })

      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(language: 'unknown', content: 'code'))
        .and_return({ 'score' => 50, 'issues' => [] })

      post '/analyze', { content: 'code', path: 'file.unknown' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
    end
  end

  describe 'GET /status' do
    it 'returns healthy statuses when downstream services respond with 200' do
      allow(HTTParty).to receive(:get)
        .with('http://localhost:8080/health', timeout: 2)
        .and_return(double(code: 200))
      allow(HTTParty).to receive(:get)
        .with('http://localhost:8081/health', timeout: 2)
        .and_return(double(code: 200))

      get '/status'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['services']['ruby']['status']).to eq('healthy')
      expect(json_response['services']['go']['status']).to eq('healthy')
      expect(json_response['services']['python']['status']).to eq('healthy')
    end

    it 'marks services as unhealthy or unreachable based on responses' do
      allow(HTTParty).to receive(:get)
        .with('http://localhost:8080/health', timeout: 2)
        .and_raise(StandardError.new('boom'))
      allow(HTTParty).to receive(:get)
        .with('http://localhost:8081/health', timeout: 2)
        .and_return(double(code: 500))

      get '/status'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['services']['go']['status']).to eq('unreachable')
      expect(json_response['services']['go']['error']).to match(/boom/)
      expect(json_response['services']['python']['status']).to eq('unhealthy')
    end
  end

  describe 'POST /diff' do
    it 'returns 400 when required fields are missing' do
      post '/diff', { old_content: 'old' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to match(/Missing old_content or new_content/)
    end

    it 'returns diff and new code review on success' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', hash_including(old_content: 'old', new_content: 'new'))
        .and_return({ 'changes' => 1, 'diff' => '@@' })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'new'))
        .and_return({ 'score' => 88, 'issues' => [] })

      post '/diff', { old_content: 'old', new_content: 'new' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['diff']).to include('changes' => 1)
      expect(json_response['new_code_review']).to include('score' => 88)
    end
  end

  describe 'POST /metrics' do
    it 'computes overall_quality based on metrics and review (positive case)' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(content: 'code'))
        .and_return({ 'complexity' => 1 })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'code'))
        .and_return({ 'score' => 90, 'issues' => ['x'] })

      post '/metrics', { content: 'code' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['overall_quality']).to eq(30.0)
    end

    it 'clamps overall_quality at 0 when penalties exceed base score' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(content: 'complex'))
        .and_return({ 'complexity' => 3 })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'complex'))
        .and_return({ 'score' => 80, 'issues' => %w[a b] })

      post '/metrics', { content: 'complex' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['overall_quality']).to eq(0)
    end

    it 'returns 0.0 overall_quality when metrics contains error' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(content: 'bad'))
        .and_return({ 'error' => 'fail' })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'bad'))
        .and_return({ 'score' => 90, 'issues' => [] })

      post '/metrics', { content: 'bad' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['overall_quality']).to eq(0.0)
      expect(json_response['metrics']).to include('error' => 'fail')
    end

    it 'returns 400 when content is missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to match(/Missing content/)
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files array is missing or empty' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to match(/Missing files array/)
    end

    it 'returns summary with computed health_score and ISO8601 timestamp' do
      files = [{ 'path' => 'a.rb', 'content' => 'puts 1' }, { 'path' => 'b.py', 'content' => 'print(1)' }]

      file_stats = {
        'total_files' => 5,
        'total_lines' => 100,
        'languages' => { 'ruby' => 1, 'python' => 1 }
      }
      review_stats = {
        'average_score' => 80.0,
        'total_issues' => 10,
        'average_complexity' => 0.5
      }
      expected_health = 80.0 - ((10.0 / 5) * 2) - (0.5 * 30)
      expected_health = [[expected_health, 0].max, 100].min.round(2)

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', hash_including(files: files))
        .and_return(file_stats)
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', hash_including(files: files))
        .and_return(review_stats)

      post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)

      expect { Time.iso8601(json_response['timestamp']) }.not_to raise_error
      expect(json_response['summary']['total_files']).to eq(5)
      expect(json_response['summary']['total_lines']).to eq(100)
      expect(json_response['summary']['languages']).to eq(file_stats['languages'])
      expect(json_response['summary']['average_quality_score']).to eq(80.0)
      expect(json_response['summary']['total_issues']).to eq(10)
      expect(json_response['summary']['health_score']).to eq(expected_health)
    end
  end
end
